import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np
from models.spectral import SpectralNorm as SpectralNormalization
from models.sagan import Self_Attn
import ipdb
import math

def get_SN(bool):
  if bool:
    return SpectralNormalization
  else:
    return lambda x:x

def print_debug(feed, layers):
  print(feed.size())
  for layer in layers:
    feed = layer(feed)
    if isinstance(layer, nn.Conv2d) or isinstance(layer, nn.ConvTranspose2d) \
                                    or isinstance(layer, ResidualBlock) \
                                    or isinstance(layer, Self_Attn) \
                                    or isinstance(layer, SpectralNormalization):
      print(str(layer).split('(')[0], feed.size())

class ResidualBlock(nn.Module):
  """Residual Block."""
  def __init__(self, dim_in, dim_out):
    super(ResidualBlock, self).__init__()
    self.main = nn.Sequential(
      nn.Conv2d(dim_in, dim_out, kernel_size=3, stride=1, padding=1, bias=False),
      nn.InstanceNorm2d(dim_out, affine=True),
      nn.ReLU(inplace=True),
      nn.Conv2d(dim_out, dim_out, kernel_size=3, stride=1, padding=1, bias=False),
      nn.InstanceNorm2d(dim_out, affine=True))

  def forward(self, x):
    return x + self.main(x)


class Generator(nn.Module):
  """Generator. Encoder-Decoder Architecture."""
  def __init__(self, image_size = 128, conv_dim=64, c_dim=5, repeat_num=6, NO_TANH=False, SAGAN=False, debug=False):
    super(Generator, self).__init__()
    layers = []
    layers.append(nn.Conv2d(3+c_dim, conv_dim, kernel_size=7, stride=1, padding=3, bias=False))
    layers.append(nn.InstanceNorm2d(conv_dim, affine=True))
    layers.append(nn.ReLU(inplace=True))

    # if SAGAN:
    #   attn1 = Self_Attn(int(self.imsize/4), 128, 'relu')
    #   attn2 = Self_Attn(int(self.imsize/2), 64, 'relu')      

    # Down-Sampling
    conv_repeat = int(math.log(image_size, 2))-5
    curr_dim = conv_dim
    for i in range(conv_repeat):
      layers.append(nn.Conv2d(curr_dim, curr_dim*2, kernel_size=4, stride=2, padding=1, bias=False))
      layers.append(nn.InstanceNorm2d(curr_dim*2, affine=True))
      layers.append(nn.ReLU(inplace=True))
      curr_dim = curr_dim * 2

    # Bottleneck
    for i in range(repeat_num):
      layers.append(ResidualBlock(dim_in=curr_dim, dim_out=curr_dim))

    # Up-Sampling
    if SAGAN: self.scores = []
    for i in range(conv_repeat):
      layers.append(nn.ConvTranspose2d(curr_dim, curr_dim//2, kernel_size=4, stride=2, padding=1, bias=False))
      layers.append(nn.InstanceNorm2d(curr_dim//2, affine=True))
      layers.append(nn.ReLU(inplace=True))
      curr_dim = curr_dim // 2
      if SAGAN and i>0:
        layers.append(Self_Attn(64*(i+1), curr_dim))  

    layers.append(nn.Conv2d(curr_dim, 3, kernel_size=7, stride=1, padding=3, bias=False))
    if not NO_TANH: layers.append(nn.Tanh())
    self.main = nn.Sequential(*layers)
    # if SAGAN:

    if debug:
      feed = Variable(torch.ones(1,3+c_dim,image_size,image_size), volatile=True)
      print('-- Generator:')
      print_debug(feed, layers)

  def forward(self, x, c):
    # replicate spatially and concatenate domain information
    c = c.unsqueeze(2).unsqueeze(3)
    c = c.expand(c.size(0), c.size(1), x.size(2), x.size(3))
    # ipdb.set_trace()
    x = torch.cat([x, c], dim=1)
    return self.main(x)


class Discriminator(nn.Module):
  """Discriminator. PatchGAN."""
  def __init__(self, image_size=256, conv_dim=64, c_dim=5, repeat_num=6, SN=False, SAGAN=False, debug=False):
    super(Discriminator, self).__init__()
    SpectralNorm = get_SN(SN)
    layers = []
    layers.append(SpectralNorm(nn.Conv2d(3, conv_dim, kernel_size=4, stride=2, padding=1)))
    layers.append(nn.LeakyReLU(0.01, inplace=True))

    curr_dim = conv_dim
    for i in range(1, repeat_num):
      layers.append(SpectralNorm(nn.Conv2d(curr_dim, curr_dim*2, kernel_size=4, stride=2, padding=1)))
      layers.append(nn.LeakyReLU(0.01, inplace=True))
      curr_dim = curr_dim * 2
      # if SAGAN and i<repeat_num-3:
      #   layers.append(Self_Attn(64*(i+1), curr_dim))        

    k_size = int(image_size / np.power(2, repeat_num))
    layers_debug = layers
    self.main = nn.Sequential(*layers)
    # ipdb.set_trace()
    self.conv1 = nn.Conv2d(curr_dim, 1, kernel_size=3, stride=1, padding=1, bias=False)
    self.conv2 = nn.Conv2d(curr_dim, c_dim, kernel_size=k_size, bias=False)
    layers_debug.append(self.conv1)
    if debug:
      feed = Variable(torch.ones(1,3,image_size,image_size), volatile=True)
      print('-- Discriminator:')
      print_debug(feed, layers_debug)


  def forward(self, x, lstm=False):
    h = self.main(x)
    # ipdb.set_trace()
    out_real = self.conv1(h).squeeze()
    out_aux = self.conv2(h).squeeze()

    return out_real.view(x.size(0), out_real.size(-2), out_real.size(-1)), out_aux.view(x.size(0), out_aux.size(-1))
