import os
import time
import torch
from PIL import Image, ImageOps
print(torch.__version__)
import piq
from model import *
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
import torch.optim as optim
from torchsummary import summary

"""### Preparing Data"""
import numpy as np
from torch.optim import Adam
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
import argparse


def read_data(path, data_size):
    data = []
    patch = []
    for dirname, _, filenames in os.walk(path):
        for filename in filenames:
            if len(data) < data_size:
                f = os.path.join(dirname, filename)
                #             print(f)
                if filename.split('.')[-1] == 'jpg':
                    img = Image.open(f)
                    img.load()
                    img_array = np.asarray(img)
                    img_array = np.swapaxes(img_array,
                                            np.where(np.asarray(img_array.shape) == min(img_array.shape))[0][0], 0)
                    data.append(img_array)
    return data

class CustomDataset(Dataset):
    def __init__(self, image_data, labels):
        self.image_data = image_data
        self.labels = labels

    def __len__(self):
        return (len(self.image_data))

    def __getitem__(self, index):
        image = self.image_data[index]
        label = self.labels[index]
        return (
            torch.tensor(image, dtype=torch.float),
            torch.tensor(label, dtype=torch.float)
        )


def data_load(all_lr_data, all_hr_data, batch_size, workers):

    # Train, Test, Validation splits
    train_data_hr = all_hr_data[:len(all_hr_data) // 3]
    train_data_lr = all_lr_data[:len(all_lr_data) // 3]
    print(f'len of train hr data ={len(train_data_hr)}')

    val_data_hr = all_hr_data[len(all_hr_data) // 3:(len(all_hr_data) // 3) + (len(all_hr_data) // 4)]
    val_data_lr = all_lr_data[len(all_lr_data) // 3:(len(all_lr_data) // 3) + (len(all_lr_data) // 4)]

    print(f'len of val hr data ={len(val_data_hr)}')

    print(f'hr {len(all_hr_data)}')
    print(f'lr {len(all_lr_data)}')

    train_data = CustomDataset(np.asarray(train_data_lr), np.asarray(train_data_hr))
    val_data = CustomDataset(np.asarray(val_data_lr), np.asarray(val_data_hr))

    print(f'dataset created')

    # Load Data as Numpy Array
    train_loader = DataLoader(train_data, batch_size=batch_size, shuffle=False, num_workers=workers)
    val_loader = DataLoader(val_data, batch_size=batch_size, shuffle=False, num_workers=workers)

    print(f'train {len(train_data_hr)}')
    print(f'val {len(val_data_hr)}')

    return train_loader, val_loader


# Initialize parser
parser = argparse.ArgumentParser()
# Adding optional argument

parser.add_argument("model", type=str, help="model to use")
parser.add_argument("hr_data", type=str, help="HR Path")
parser.add_argument("lr_data", type=str, help="LR Path")
parser.add_argument("batch_size", type=int, help="batch size")
parser.add_argument("workers", type=int, help="workers")
parser.add_argument("result", type=str, help="result Path (to save)")
parser.add_argument("scale", type=int, help="downsampling scale")
parser.add_argument("epochs", type=int, help="epochs")
parser.add_argument("name", type=str, help="model name")
parser.add_argument("data_size", type=int, help="data size")
# Read arguments from command line
args = parser.parse_args()
# -
data_size = args.data_size
model_to_use = args.model
res_path = args.result
scale = args.scale
epochs = args.epochs
name = args.name
hr_path = args.hr_data
lr_path = args.lr_data
batch_size = args.batch_size
workers = args.workers

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

if not os.path.exists(res_path):
    os.makedirs(res_path)

all_hr_data = read_data(hr_path, data_size)
all_lr_data = read_data(lr_path, data_size)
print('read')
train_loader, val_loader = data_load(all_lr_data,all_hr_data, batch_size, workers)
print('loaded')

print('Computation device: ', device)

if model_to_use == 'mdpvsr':
    model = mdpvsr(num_channels=train_loader.dataset[0][0].shape[0], num_kernels=train_loader.dataset[0][0].shape[1]//2,
               kernel_size=(3,3), padding=(1, 1), scale=scale).to(device)

elif model_to_use == 'mduvsr_6defconv':
    model = mduvsr_6defconv(num_channels=train_loader.dataset[0][0].shape[0], num_kernels=train_loader.dataset[0][0].shape[1]//2,
               kernel_size=(3,3), padding=(1, 1), scale=scale).to(device)

elif model_to_use == 'mduvsr_6defconv_pixelshuff':
    model = mduvsr_6defconv_pixelshuff(num_channels=train_loader.dataset[0][0].shape[0], num_kernels=train_loader.dataset[0][0].shape[1] // 2,
    kernel_size=(3, 3), padding = (1, 1), scale = scale).to(device)

else:
    model = mduvsr(num_channels=train_loader.dataset[0][0].shape[0],
                   num_kernels=train_loader.dataset[0][0].shape[1] // 2,
                   kernel_size=(3, 3), padding=(1, 1), scale=scale).to(device)



print(model)
print(summary(model, (train_loader.dataset[0][0].shape)))
"""### Loss Function"""


def get_outnorm(x: torch.Tensor, out_norm: str = '') -> torch.Tensor:
    """ Common function to get a loss normalization value. Can
        normalize by either the batch size ('b'), the number of
        channels ('c'), the image size ('i') or combinations
        ('bi', 'bci', etc)
    """
    # b, c, h, w = x.size()
    img_shape = x.shape

    if not out_norm:
        return 1

    norm = 1
    if 'b' in out_norm:
        # normalize by batch size
        # norm /= b
        norm /= img_shape[0]
    if 'c' in out_norm:
        # normalize by the number of channels
        # norm /= c
        norm /= img_shape[-3]
    if 'i' in out_norm:
        # normalize by image/map size
        # norm /= h*w
        norm /= img_shape[-1] * img_shape[-2]

    return norm


class CharbonnierLoss(nn.Module):
    """Charbonnier Loss (L1)"""

    def __init__(self, eps=1e-6, out_norm: str = 'bci'):
        super(CharbonnierLoss, self).__init__()
        self.eps = eps
        self.out_norm = out_norm

    def forward(self, x, y):
        norm = get_outnorm(x, self.out_norm)
        loss = torch.sum(torch.sqrt((x - y).pow(2) + self.eps ** 2))
        return loss * norm


"""### Training"""

scaler = torch.cuda.amp.GradScaler()
optimizer = optim.AdamW(model.parameters(), lr=0.001, betas=(0.9, 0.999), eps=1e-08, weight_decay=0.01, amsgrad=False)

# criterion = nn.L1Loss()
criterion = CharbonnierLoss()
num_epochs = epochs

"""### Training"""

for epoch in range(num_epochs//2):
    state = (None, None)
    c=0
    train_loss = 0
    ssim_best = 0
    psnr, ssim =0, 0
    model.train()

    st = time.time()
    for batch_num, data in enumerate(train_loader, 0):

        input, target = data[0].to(device), data[1]
        optimizer.zero_grad()
        state = model(input.cuda(), state[1])
        state[1][0].detach_()
        state[1][1].detach_()
        output = state[0]
        with torch.cuda.amp.autocast():
            loss = criterion(output.cuda(), target.cuda())
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        train_loss += loss.item()
        if batch_num % 10 ==0 :
            c+=1
            psnr += piq.psnr(output.cpu(), target, data_range=255., reduction='mean')
            ssim += piq.ssim(output.cpu(), target, data_range=255.)
            # print(f'batch_num {batch_num}')
        # lpips.append(piq.LPIPS(reduction='mean')(torch.clamp(output, 0, 1), torch.clamp(target.cuda(), 0, 255)))
        # torch.cuda.empty_cache()
    train_loss /= len(train_loader.dataset)
    psnr_avg= psnr/c
    ssim_avg= ssim/c

    val_loss = 0
    model.eval()
    with torch.no_grad():
        for input, target in val_loader:
            output, _ = model(input.cuda())
            loss = criterion(output.cuda(), target.cuda())
            # lpips_test.append(piq.LPIPS(reduction='mean')(torch.clamp(output, 0, 1), torch.clamp(target.cuda(), 0, 255)))
            val_loss += loss.item()

    val_loss /= len(val_loader.dataset)

    print("Epoch:{} Training Loss:{:.2f} Validation Loss:{:.2f} in {:.2f} and SSIM\n".format(
        epoch+1, train_loss, val_loss, time.time()-st))
    print(f'Train PSNR avg {psnr_avg}')
    print(f'Train SSIM avg {ssim_avg}')

    if ssim_avg > ssim_best:
        ssim_best = ssim_avg
        params = f'{epochs} epochs, charbonnier, 1 dfup,1 convlstm, 3 deformable,' \
                 f'kernel_size={(3, 3)}, padding={(1, 1)}, activation={"relu"},' \
                 f'scale={scale}  {name}'
        PATH = f'{res_path}/mdu-vsr-customdataser-{params}.pth'
        torch.save(model.state_dict(), PATH)
        model.load_state_dict(torch.load(PATH))

optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)

for epoch in range(num_epochs//2):
    state = (None, None)
    c = 0
    train_loss = 0
    ssim_best = 0
    psnr, ssim = 0, 0
    model.train()
    st = time.time()
    for batch_num, data in enumerate(train_loader, 0):

        input, target = data[0].to(device), data[1]
        optimizer.zero_grad()
        state = model(input.cuda(), state[1])
        state[1][0].detach_()
        state[1][1].detach_()
        output = state[0]
        with torch.cuda.amp.autocast():
            loss = criterion(output.cuda(), target.cuda())
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        train_loss += loss.item()
        if batch_num % 10 ==0 :
            c += 1
            psnr += piq.psnr(output.cpu(), target, data_range=255., reduction='mean')
            ssim += piq.ssim(output.cpu(), target, data_range=255.)
            # print(f'batch_num {batch_num}')
        # torch.cuda.empty_cache()
    train_loss /= len(train_loader.dataset)

    psnr_avg= psnr/c
    ssim_avg= ssim/c

    val_loss = 0
    model.eval()
    with torch.no_grad():
        for input, target in val_loader:
            output, _ = model(input.cuda())
            res = output.cpu()[-1][0].detach().numpy()
            plt.imshow(res)
            plt.savefig(f"{res_path}/epoch_{epoch}.png", bbox_inches="tight", pad_inches=0.0)
            loss = criterion(output.cuda(), target.cuda())
            val_loss += loss.item()

    val_loss /= len(val_loader.dataset)

    print("Epoch:{} Training Loss:{:.2f} Validation Loss:{:.2f} in {:.2f} and SSIM\n".format(
        epoch+num_epochs//2, train_loss, val_loss, time.time()-st))
    print(f'Train PSNR avg {psnr_avg}')
    print(f'Train SSIM avg {ssim_avg} ')

    if ssim_avg > ssim_best:
        ssim_best = ssim_avg
        params = f'{epochs} epochs, charbonnier, 1 dfup,1 convlstm, 3 deformable ' \
                 f'kernel_size={(3, 3)}, padding={(1, 1)}, activation={"relu"},' \
                 f'scale={scale}  {name}'
        PATH = f'{res_path}/mdu-vsr-customdataset-{params}.pth'
        torch.save(model.state_dict(), PATH)
        model.load_state_dict(torch.load(PATH))





# test_loader = torch.load('test_loader.pt', map_location=torch.device('cuda'))
# model.eval()
# ssim_val = []
# psnr_val = []
# lpips_val = []
# running_psnr = 0
#
# with torch.no_grad():
#     for input, target in test_loader:
#         output = model(input.cuda())
#         psnr_val.append(piq.psnr(output, target.cuda(), data_range=255., reduction='mean'))
#         ssim_val.append(piq.ssim(output, target.cuda(), data_range=255.))
#         lpips_val.append(piq.LPIPS(reduction='mean')(torch.clamp(output, 0, 1), torch.clamp(target.cuda(), 0, 255)))
#
#         print(f'psnr value ={psnr_val[-1]}')
#         print(f'ssim value ={ssim_val[-1]}')
#         print(f'lpips value ={lpips_val[-1]}')
#
#     with open(r'name_quality metrics', 'w') as fp:
#         fp.write("\n PSNR")
#         for item in psnr_val:
#             # write each item on a new line
#             fp.write("%s\n" % item)
#
#         fp.write("\n SSIM")
#         for item in ssim_val:
#             # write each item on a new line
#             fp.write("%s\n" % item)
#
#         fp.write("\n LPIPS")
#         for item in lpips_val:
#             # write each item on a new line
#             fp.write("%s\n" % item)


