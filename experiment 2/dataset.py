import os

from PIL import Image
from torch.utils.data import Dataset


class CityscapesDataset(Dataset):
    # "name", "id", "train_id", "category", "category_id", "has_instances", "ignore_in_eval", "color"
    classes = [
        ("unlabeled", 0, 255, "void", 0, False, True, (0, 0, 0)),
        ("ego vehicle", 1, 255, "void", 0, False, True, (0, 0, 0)),
        ("rectification border", 2, 255, "void", 0, False, True, (0, 0, 0)),
        ("out of roi", 3, 255, "void", 0, False, True, (0, 0, 0)),
        ("static", 4, 255, "void", 0, False, True, (0, 0, 0)),
        ("dynamic", 5, 255, "void", 0, False, True, (111, 74, 0)),
        ("ground", 6, 255, "void", 0, False, True, (81, 0, 81)),
        ("road", 7, 0, "flat", 1, False, False, (128, 64, 128)),
        ("sidewalk", 8, 1, "flat", 1, False, False, (244, 35, 232)),
        ("parking", 9, 255, "flat", 1, False, True, (250, 170, 160)),
        ("rail track", 10, 255, "flat", 1, False, True, (230, 150, 140)),
        ("building", 11, 2, "construction", 2, False, False, (70, 70, 70)),
        ("wall", 12, 3, "construction", 2, False, False, (102, 102, 156)),
        ("fence", 13, 4, "construction", 2, False, False, (190, 153, 153)),
        ("guard rail", 14, 255, "construction", 2, False, True, (180, 165, 180)),
        ("bridge", 15, 255, "construction", 2, False, True, (150, 100, 100)),
        ("tunnel", 16, 255, "construction", 2, False, True, (150, 120, 90)),
        ("pole", 17, 5, "object", 3, False, False, (153, 153, 153)),
        ("polegroup", 18, 255, "object", 3, False, True, (153, 153, 153)),
        ("traffic light", 19, 6, "object", 3, False, False, (250, 170, 30)),
        ("traffic sign", 20, 7, "object", 3, False, False, (220, 220, 0)),
        ("vegetation", 21, 8, "nature", 4, False, False, (107, 142, 35)),
        ("terrain", 22, 9, "nature", 4, False, False, (152, 251, 152)),
        ("sky", 23, 10, "sky", 5, False, False, (70, 130, 180)),
        ("person", 24, 11, "human", 6, True, False, (220, 20, 60)),
        ("rider", 25, 12, "human", 6, True, False, (255, 0, 0)),
        ("car", 26, 13, "vehicle", 7, True, False, (0, 0, 142)),
        ("truck", 27, 14, "vehicle", 7, True, False, (0, 0, 70)),
        ("bus", 28, 15, "vehicle", 7, True, False, (0, 60, 100)),
        ("caravan", 29, 255, "vehicle", 7, True, True, (0, 0, 90)),
        ("trailer", 30, 255, "vehicle", 7, True, True, (0, 0, 110)),
        ("train", 31, 16, "vehicle", 7, True, False, (0, 80, 100)),
        ("motorcycle", 32, 17, "vehicle", 7, True, False, (0, 0, 230)),
        ("bicycle", 33, 18, "vehicle", 7, True, False, (119, 11, 32)),
        ("license plate", -1, -1, "vehicle", 7, False, True, (0, 0, 142))
    ]

    def __init__(self, root_folder: str, subset: str):
        self.root_folder = root_folder
        self.subset = subset

        self.image_folder = os.path.join(self.root_folder, 'leftImg8bit', self.subset)
        self.mask_folder = os.path.join(self.root_folder, 'gtFine', self.subset)

        self.files = []
        for city in os.listdir(self.image_folder):
            images = os.path.join(self.image_folder, city)
            masks = os.path.join(self.mask_folder, city)
            for image in os.listdir(images):
                mask = os.path.join(masks, f"{image.split('_leftImg8bit')[0]}_gtFine_labelIds.png")
                self.files.append((image, mask))

    def __len__(self):
        return len(self.files)

    def __getitem__(self, index):
        image_path, mask_path = self.files[index]

        image = Image.open(image_path)
        mask = Image.open(mask_path)

        return image, mask