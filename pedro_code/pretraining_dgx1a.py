import pandas as pd
import numpy as np
import pydicom
from PIL import Image
import glob
import os
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
import matplotlib.pyplot as plt

import torch
import torchvision
from torchvision import datasets, transforms, models
from torch.utils.data import DataLoader, Dataset
import torch.nn as nn
import torch.nn.functional as F
import argparse
from efficientnet_pytorch import EfficientNet
from torch.utils.tensorboard import SummaryWriter

# Writer will output to ./runs/ directory by default
log_dir = f'/nfs/home/pedro/COVID/logs/{os.path.basename(__file__)[:-3]}'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
writer = SummaryWriter(log_dir=log_dir)

parser = argparse.ArgumentParser(description='Passing files + relevant directories')
parser.add_argument('--labels', nargs='+', type=str)
parser.add_argument('--images_dir', nargs='+', type=str)
arguments = parser.parse_args()


def default_image_loader(path):
    img = Image.open(path).convert('RGB')
    return img


def dicom_image_loader(path):
    ds = pydicom.dcmread(path)
    img = ds.pixel_array.astype(np.float32)
    img -= img.min()
    img /= img.max()
    img = np.uint8(255.0*img)
    img = Image.fromarray(img).convert("RGB")
    return img


def image_normaliser(some_image):
    return 255 * (some_image - torch.min(some_image)) / (torch.max(some_image) - torch.min(some_image))


class ImageDataset(Dataset):
    def __init__(self, df, transform):
        self.df = df
        self.loader = default_image_loader
        self.transform = transform

    def __getitem__(self, index):
        image_name = self.df['Image Index'][index]
        filepath = image_name
        image = self.loader(filepath)
        image = self.transform(image)
        label = self.df['OHE Finding'][index]
        label = np.array(label)
        return image, filepath, label

    def __len__(self):
        return self.df.shape[0]


# Paths
img_dir = arguments.images_dir  # '/nfs/home/pedro/COVID/Data/KCH_CXR_JPG'
img_dir = img_dir[0]
labels = arguments.labels  # '/nfs/home/pedro/COVID/Labels/KCH_CXR_JPG.csv'
# img_dir = '/data/COVID/Data/ChestXray-NIHCC/images'
# labels = '/data/COVID/Data/ChestXray-NIHCC/Data_Entry_2017.csv'
print(img_dir)
print(labels)
SAVE_PATH = os.path.join(f'/nfs/home/pedro/COVID/models/{os.path.basename(__file__)[:-3]}')
if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH)
SAVE = True
LOAD = False

# Hyperparameter loading
if LOAD:
    model_files = glob.glob(os.path.join(SAVE_PATH, '*.pth'))
    latest_model_file = max(model_files, key=os.path.getctime)
    checkpoint = torch.load(latest_model_file)
    encoder = checkpoint['encoder']
    loaded_epoch = checkpoint['epoch']
    loss = checkpoint['loss']
    running_iter = checkpoint['running_iter']
    # Extras that may not exist in older models
    bs = checkpoint['batch_size']
    input_size = checkpoint['resolution']
    EPOCHS = 100
else:
    running_iter = 0
    loaded_epoch = -1
    bs = 128
    input_size = (256, 256)
    encoder = 'efficientnet-b0'
    EPOCHS = 100


# Load labels
df = pd.read_csv(labels[0])
# Uniques
label_uniques = df['Finding Labels'].unique()
disease_uniques = []
for label_unique in label_uniques:
    disease_uniques.extend(label_unique.split("|"))
# Create list with all individual diseases
disease_uniques = sorted(set(disease_uniques))
# Remove the No Finding label since that corresponds to no diseases
disease_uniques.remove('No Finding')
print(disease_uniques)
# Length is the number of classes
num_classes = len(disease_uniques)

# Convert to one hot encodings
ohe_labels = []
disease_labels = df['Finding Labels']
for disease_label in disease_labels:
    ohe_label = []
    for ID, disease in enumerate(disease_uniques):
        if disease in disease_label:
            ohe_label.append(1.0)
        else:
            ohe_label.append(0.0)
    ohe_labels.append(ohe_label)

# Add to dataframe
df['OHE Finding'] = ohe_labels
print(f'The Number of images: is {df.shape[0]}')

# Edit Image Index to include image directory
df['Image Index'] = img_dir + '/' + df['Image Index']


# The network
class Model(nn.Module):
    def __init__(self, encoder='efficientnet-b3'):
        super(Model, self).__init__()
        n_channels_dict = {'efficientnet-b0': 1280, 'efficientnet-b1': 1280, 'efficientnet-b2': 1408,
                           'efficientnet-b3': 1536, 'efficientnet-b4': 1792, 'efficientnet-b5': 2048,
                           'efficientnet-b6': 2304, 'efficientnet-b7': 2560}
        params_dict = {
            # Coefficients:   width,depth,res,dropout
            'efficientnet-b0': (1.0, 1.0, 224, 0.2),
            'efficientnet-b1': (1.0, 1.1, 240, 0.2),
            'efficientnet-b2': (1.1, 1.2, 260, 0.3),
            'efficientnet-b3': (1.2, 1.4, 300, 0.3),
            'efficientnet-b4': (1.4, 1.8, 380, 0.4),
            'efficientnet-b5': (1.6, 2.2, 456, 0.4),
            'efficientnet-b6': (1.8, 2.6, 528, 0.5),
            'efficientnet-b7': (2.0, 3.1, 600, 0.5),
            'efficientnet-b8': (2.2, 3.6, 672, 0.5),
            'efficientnet-l2': (4.3, 5.3, 800, 0.5),
        }
        #self.net = EfficientNet.from_pretrained(encoder)
        #self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.net = EfficientNet.from_pretrained(encoder, num_classes=num_classes)
        # self.net = EfficientNet()

    def forward(self, x):
        #x = self.net.extract_features(x)
        #x = self.avg_pool(x)
        #out = nn.Flatten()(x)
        out = self.net(x)
        return out


# Model definition
model = Model(encoder)
use_cuda = torch.cuda.is_available()
print('Using cuda', use_cuda)

if use_cuda and torch.cuda.device_count() > 1:
    print('Using', torch.cuda.device_count(), 'GPUs!')
model = nn.DataParallel(model)

# criterion = nn.BCEWithLogitsLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.0001)
scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, 0.9)


# Model specific loading
if LOAD:
    model.load_state_dict(checkpoint['model_state_dict'])
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    scheduler.load_state_dict(checkpoint['scheduler_state_dict'])


# Train / Val split
train_df, val_df = train_test_split(df, test_size=0.10)
train_df.reset_index(drop=True, inplace=True)
val_df.reset_index(drop=True, inplace=True)

print(f'The length of the training is {len(train_df)}')
print(f'The length of the validation is {len(val_df)}')

mean = [0.485, 0.456, 0.406]
std = [0.229, 0.224, 0.225]
transform = transforms.Compose([
    transforms.Resize(input_size, 3),
    transforms.ToTensor(),
    transforms.Normalize(mean, std)
])

train_dataset = ImageDataset(train_df, transform)
train_loader = DataLoader(train_dataset, batch_size=bs, num_workers=8, shuffle=True)

val_dataset = ImageDataset(val_df, transform)
val_loader = DataLoader(val_dataset, batch_size=bs, num_workers=8)


model.cuda()
print('\nStarting training!')
for epoch in range(loaded_epoch+1, EPOCHS):
    print('Training step')
    running_loss = 0.0
    model.train()
    correct = 0
    total = 0

    for i, sample in enumerate(train_loader):
        images, names, labels = sample
        # print(images.shape, labels.shape)
        images = images.cuda()
        labels = labels.cuda()

        out = model(images)

        labels = labels.float()
        # See: https://openaccess.thecvf.com/content_cvpr_2017/papers/Wang_ChestX-ray8_Hospital-Scale_Chest_CVPR_2017_paper.pdf (Equation 1)
        # Also:https://pytorch.org/docs/stable/_modules/torch/nn/modules/loss.html#BCEWithLogitsLoss (pos_weight)
        pos_weighting = labels[labels == 0.0].numel() / labels[labels == 1.0].numel()
        pos_weighting = torch.tensor(pos_weighting).repeat(num_classes).cuda()
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weighting)
        loss = criterion(out, labels)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        running_loss += loss.item()

        total += labels.size(0)
        out = torch.sigmoid(out)
        correct += ((out > 0.5).int() == labels).sum().item()

        grid = torchvision.utils.make_grid(images)
        writer.add_image('images', grid, 0)

        # Convert labels and output to grid
        images_grid = torchvision.utils.make_grid(images)
        labels_grid = torchvision.utils.make_grid(labels)
        rounded_output_grid = torchvision.utils.make_grid((out > 0.5).int())
        output_grid = torchvision.utils.make_grid(out)

        # Writing to tensorboard
        if running_iter % 20 == 0:
            writer.add_scalar('Loss/train', loss.item(), running_iter)
            writer.add_image('Visuals/Images', image_normaliser(images_grid), running_iter)
            writer.add_image('Visuals/Labels', labels_grid, running_iter)
            writer.add_image('Visuals/Rounded Output', rounded_output_grid, running_iter)
            writer.add_image('Visuals/Output', output_grid, running_iter)
        print("iter: {}, Loss: {}".format(running_iter, loss.item()))
        running_iter += 1

    print("Epoch: {}, Loss: {}, Train Accuracy: {}".format(epoch, running_loss, round(correct / (total * num_classes), 4)))
    if epoch % 2 == 1:
        scheduler.step()

    # Save model
    if SAVE:
        MODEL_PATH = os.path.join(SAVE_PATH, f'model_epoch_{epoch}.pth')
        print(MODEL_PATH)
        torch.save({'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'scheduler_state_dict': scheduler.state_dict(),
                    'epoch': epoch,
                    'loss': loss,
                    'running_iter': running_iter,
                    'encoder': encoder,
                    'batch_size': bs,
                    'resolution': input_size}, MODEL_PATH)

    print('Validation step')
    model.eval()
    running_loss = 0
    correct = 0
    total = 0
    res_id = []
    res_prob = []
    res_label = []

    for images, names, labels in val_loader:
        # Saliency plots
        # Pre-process the image
        image = images[0, ...][None, ...]

        # we need to find the gradient with respect to the input image, so we need to call requires_grad_ on it
        image.requires_grad_()
        image_grid = torchvision.utils.make_grid(image)

        # Write to tensorboard
        writer.add_image('Visuals/Sal_Image', image_normaliser(image_grid), running_iter)

        '''
        forward pass through the model to get the scores, note that VGG-19 model doesn't perform softmax at the end
        and we also don't need softmax, we need scores, so that's perfect for us.
        '''

        scores = model(image)

        # Get the index corresponding to the maximum score and the maximum score itself.
        score_max_index = scores.argmax()
        score_max = scores[0, score_max_index]
        # var_score_max = torch.autograd.Variable(score_max, requires_grad=True)

        '''
        backward function on score_max performs the backward pass in the computation graph and calculates the gradient of 
        score_max with respect to nodes in the computation graph
        '''
        score_max.backward()

        '''
        Saliency would be the gradient with respect to the input image now. But note that the input image has 3 channels,
        R, G and B. To derive a single class saliency value for each pixel (i, j),  we take the maximum magnitude
        across all colour channels.
        '''
        saliency, _ = torch.max(image.grad.data.abs(), dim=1)
        saliency_grid = torchvision.utils.make_grid(saliency[0])

        # Write to tensorboard
        writer.add_image('Visuals/Saliency', image_normaliser(saliency_grid), running_iter)
        break

    with torch.no_grad():
        for images, names, labels in val_loader:
            images = images.cuda()
            labels = labels.cuda()
            labels = labels.float()
            out = model(images)
            loss = criterion(out.data, labels)

            running_loss += loss.item()

            total += labels.size(0)
            out = torch.sigmoid(out)
            correct += ((out > 0.5).int() == labels).sum().item()

            res_id += names
            res_prob += out.cpu().numpy().tolist()
            res_label += labels.cpu().numpy().tolist()

            # Write to tensorboard
            writer.add_scalar('Loss/val', loss.item(), running_iter)

    acc = correct / (total * num_classes)
    y_true = np.array(res_label)
    y_scores = np.array(res_prob)
    auc = roc_auc_score(y_true, y_scores)
    print("Epoch: {}, Loss: {}, Test Accuracy: {}, AUC: {}\n".format(epoch, running_loss, round(acc, 4), auc))

print('END')


# # Saliency maps
# # preprocess the image
# for images, names, labels in val_loader:
#
#     # Pre-process the image
#     image = images[0, ...][None, ...]
#
#     # we would run the model in evaluation mode
#     model.eval()
#
#     # we need to find the gradient with respect to the input image, so we need to call requires_grad_ on it
#     image.requires_grad_()
#
#     '''
#     forward pass through the model to get the scores, note that VGG-19 model doesn't perform softmax at the end
#     and we also don't need softmax, we need scores, so that's perfect for us.
#     '''
#
#     scores = model(image)
#
#     # Get the index corresponding to the maximum score and the maximum score itself.
#     score_max_index = scores.argmax()
#     score_max = scores[0, score_max_index]
#
#     '''
#     backward function on score_max performs the backward pass in the computation graph and calculates the gradient of
#     score_max with respect to nodes in the computation graph
#     '''
#     score_max.backward()
#
#     '''
#     Saliency would be the gradient with respect to the input image now. But note that the input image has 3 channels,
#     R, G and B. To derive a single class saliency value for each pixel (i, j),  we take the maximum magnitude
#     across all colour channels.
#     '''
#     saliency, _ = torch.max(image.grad.data.abs(), dim=1)
#
#     # code to plot the saliency map as a heatmap
#     plt.imshow(saliency[0], cmap=plt.cm.hot)
#     plt.axis('off')
#     break
# plt.show()