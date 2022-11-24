import math
import os
from functools import partial

from typing import Union
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.cuda.amp import GradScaler
from torch.utils.data import DataLoader
from tqdm import tqdm

from . import losses
from . import metrics
from .losses import LossHistory


def yolox_warm_cos_lr(lr, min_lr, total_iters, warmup_total_iters, warmup_lr_start, no_aug_iter, iters):
    if iters <= warmup_total_iters:
        # lr = (lr - warmup_lr_start) * iters / float(warmup_total_iters) + warmup_lr_start
        lr = (lr - warmup_lr_start) * pow(iters / float(warmup_total_iters), 2) + warmup_lr_start
    elif iters >= total_iters - no_aug_iter:
        lr = min_lr
    else:
        lr = min_lr + 0.5 * (lr - min_lr) * (1.0 + math.cos(
            math.pi * (iters - warmup_total_iters) / (total_iters - warmup_total_iters - no_aug_iter)))
    return lr


def step_lr(lr, decay_rate, step_size, iters):
    if step_size < 1:
        raise ValueError('step_size must above 1.')
    n = iters // step_size
    out_lr = lr * decay_rate ** n
    return out_lr


def get_lr_scheduler(lr_decay_type, lr, min_lr, total_iters, warmup_iters_ratio=0.1, warmup_lr_ratio=0.1,
                     no_aug_iter_ratio=0.3, step_num=10):
    if lr_decay_type == 'cos':
        warmup_total_iters = min(max(warmup_iters_ratio * total_iters, 1), 3)
        warmup_lr_start = max(warmup_lr_ratio * lr, 1e-6)
        no_aug_iter = min(max(no_aug_iter_ratio * total_iters, 1), 15)
        func = partial(yolox_warm_cos_lr, lr, min_lr, total_iters, warmup_total_iters, warmup_lr_start, no_aug_iter)
    else:
        decay_rate = (min_lr / lr) ** (1 / (step_num - 1))
        step_size = total_iters / step_num
        func = partial(step_lr, lr, decay_rate, step_size)
    return func


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


def one_epoch(epoch: int, epoch_max: int, model: nn.Module, net: nn.Module, optimizer: optim.Optimizer,
              num_classes: int, class_weights: np.ndarray, scaler: Union[GradScaler, None],
              train_loader: DataLoader, validate_loader: DataLoader, length_train: int, length_validate: int,
              use_cuda: bool, use_fp16: bool, use_dice_loss: bool, use_focal_loss: bool,
              history: LossHistory,
              save_period: int, save_path: str, local_rank: int = 0):
    total_loss = 0
    total_f_score = 0

    validate_loss = 0
    validate_f_score = 0

    # def debug(**kwargs):
    #     for name, value in kwargs.items():
    #         if not isinstance(value, torch.Tensor):
    #             print(f'{name}: is not a Tensor')
    #         print(f'{name}: Requires grad: {value.requires_grad}, Grad function: {value.grad_fn}')

    # noinspection PyTypeChecker
    def one_generation(source, length, is_validation: bool, process_bar: tqdm = None):
        generation_loss = 0
        generation_f_score = 0
        for iteration, batch in enumerate(source):
            if iteration >= length:
                break
            imgs, pngs, labels = batch
            # debug(imgs=imgs, pngs=pngs, labels=labels)

            with torch.no_grad():
                weights = torch.from_numpy(class_weights)
                if use_cuda:
                    imgs = imgs.cuda(local_rank)
                    pngs = pngs.cuda(local_rank)
                    labels = labels.cuda(local_rank)
                    weights = weights.cuda(local_rank)
                # debug(imgs=imgs, pngs=pngs, labels=labels, weights=weights)

            if not is_validation:
                optimizer.zero_grad()

            def forward():
                outputs = model(imgs)
                # debug(outputs=outputs)
                if use_focal_loss:
                    _loss = losses.focal(outputs, pngs, weights, num_classes=num_classes)
                else:
                    _loss = losses.ce(outputs, pngs, weights, num_classes=num_classes)

                if use_dice_loss:
                    _loss = _loss + losses.dice(outputs, labels)

                if not is_validation:
                    with torch.no_grad():
                        _f_score = metrics.f_score(outputs, labels)
                else:
                    _f_score = metrics.f_score(outputs, labels)
                return _loss, _f_score

            if is_validation or not use_fp16:
                loss, f_score = forward()
            else:
                from torch.cuda.amp import autocast
                with autocast():
                    loss, f_score = forward()

            # debug(loss=loss, f_score=f_score)

            if not is_validation:
                if use_fp16 and scaler is not None:
                    scaler.scale(loss).backward()
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    loss.backward()
                    optimizer.step()

            generation_loss += loss.item()
            generation_f_score += f_score.item()

            if local_rank == 0 and process_bar is not None:
                process_bar.set_postfix(**{
                    'loss': generation_loss / (iteration + 1),
                    'f_score': generation_f_score / (iteration + 1),
                    'lr': get_lr(optimizer)
                })
                process_bar.update(1)
        return generation_loss, generation_f_score

    bar = None
    if local_rank == 0:
        print('===== Train started')
        bar = tqdm(total=length_train, desc=f'Epoch {epoch + 1}/{epoch_max}', postfix=dict, mininterval=0.3)

    model.train()
    train_loss, train_f_score = one_generation(train_loader, length_train, False, bar)
    total_loss += train_loss
    total_f_score += train_f_score

    if local_rank == 0:
        bar.close()
        print('===== Train finished')
        print('=== Validation started')
        bar = tqdm(total=length_validate, desc=f'Epoch {epoch + 1}/{epoch_max}', postfix=dict, mininterval=0.3)

    model.eval()
    val_loss, val_f_score = one_generation(validate_loader, length_validate, True, bar)
    validate_loss += val_loss
    validate_f_score += val_f_score

    if local_rank == 0:
        bar.close()
        print('=== Validation finished')
        history.append(epoch + 1, total_loss / length_train, validate_loss / length_validate)
        # eval_callback.on_epoch_end(epoch + 1, model_train)
        print('Epoch:' + str(epoch + 1) + '/' + str(epoch_max))
        print('Total Loss: %.3f || Val Loss: %.3f ' % (total_loss / length_train, validate_loss / length_validate))

        if (epoch + 1) % save_period == 0 or epoch + 1 == epoch_max:
            torch.save(model.state_dict(), os.path.join(save_path, 'Epoch({0})-Train({1:.3f})-Validate({2:.3f})'.format(
                epoch + 1,
                total_loss / length_train,
                validate_loss / length_validate
            )))

        if len(history.validate_losses) <= 1 or (val_loss / length_validate) <= min(history.validate_losses):
            print('保存性能最好的模型至 best_epoch_weights.pth')
            torch.save(model.state_dict(), os.path.join(save_path, "Best_epoch_weights.pth"))
        torch.save(net.state_dict(), os.path.join(save_path, "Last_epoch_weights.pth"))
