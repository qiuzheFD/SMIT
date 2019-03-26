import torch
import torch.nn as nn
from models.utils import print_debug as _print_debug
from misc.utils import PRINT, to_var
from misc.blocks import (ResidualBlock, LayerNorm)
from collections import OrderedDict


# ==================================================================#
# ==================================================================#
class Generator(nn.Module):
    def __init__(self, config, debug=False, **kwargs):
        super(Generator, self).__init__()
        layers = []
        repeat_num = config.g_repeat_num
        self.config = config
        self.image_size = config.image_size
        self.c_dim = config.c_dim
        self.color_dim = config.color_dim
        self.style_dim = config.style_dim
        self.Deterministic = config.DETERMINISTIC

        layers = []

        conv_repeat = 3

        conv_dim = config.g_conv_dim
        layers += [] if config.image_size <= 512 else [
            ('down_nn_512', nn.Upsample(scale_factor=0.5, mode='bilinear'))
        ]
        layers += [] if config.image_size <= 256 else [
            ('down_nn_256', nn.Upsample(scale_factor=0.5, mode='bilinear'))
        ]
        conv = nn.Conv2d(
            self.color_dim,
            conv_dim,
            kernel_size=7,
            stride=1,
            padding=3,
            bias=False)
        layers += [('down_conv_' + str(conv_dim), conv)]
        IN = nn.InstanceNorm2d(conv_dim, affine=True)
        layers += [('down_norm_' + str(conv_dim), IN)]
        layers += [('down_relu_' + str(conv_dim), nn.ReLU(inplace=True))]

        # Down-Sampling
        curr_dim = conv_dim
        for i in range(conv_repeat):
            conv = nn.Conv2d(
                curr_dim,
                curr_dim * 2,
                kernel_size=4,
                stride=2,
                padding=1,
                bias=False)
            layers += [('down_conv_' + str(curr_dim * 2), conv)]
            IN = nn.InstanceNorm2d(curr_dim * 2, affine=True)
            layers += [('down_norm_' + str(curr_dim * 2), IN)]
            layers += [('down_relu_' + str(curr_dim * 2),
                        nn.ReLU(inplace=True))]
            curr_dim = curr_dim * 2

        # Bottleneck
        for i in range(repeat_num):
            RB = ResidualBlock(dim_in=curr_dim, dim_out=curr_dim, AdaIn=True)
            layers += [('res_{}_{}'.format(curr_dim, i), RB)]

        # # Up-Sampling
        for i in range(conv_repeat):
            if self.config.DECONV:
                conv = nn.ConvTranspose2d(
                    curr_dim,
                    curr_dim // 2,
                    kernel_size=4,
                    stride=2,
                    padding=1,
                    bias=False)
                layers += [('up_conv_' + str(curr_dim // 2), conv)]
            else:
                up = nn.Upsample(scale_factor=2, mode='bilinear')
                layers += [('up_nn_' + str(curr_dim), up)]
                conv = nn.Conv2d(
                    curr_dim,
                    curr_dim // 2,
                    kernel_size=3,
                    stride=1,
                    padding=1,
                    bias=False)
                layers += [('up_conv_' + str(curr_dim // 2), conv)]

            if not self.Deterministic:
                norm = LayerNorm(curr_dim // 2)
            else:
                norm = nn.InstanceNorm2d(curr_dim // 2, affine=True)

            layers += [('up_norm_' + str(curr_dim // 2), norm)]
            layers += [('up_relu_' + str(curr_dim // 2),
                        nn.ReLU(inplace=True))]
            curr_dim = curr_dim // 2

        self.main = nn.Sequential(OrderedDict(layers))

        fake_conv = nn.Conv2d(
            curr_dim,
            self.color_dim,
            kernel_size=7,
            stride=1,
            padding=3,
            bias=False)
        layers = [('fake', fake_conv)]
        layers += [] if config.image_size <= 256 else [
            ('fake_up_nn_512', nn.Upsample(scale_factor=2, mode='bilinear'))
        ]
        layers += [] if config.image_size <= 512 else [
            ('fake_up_nn_1024', nn.Upsample(scale_factor=2, mode='bilinear'))
        ]
        layers += [('tanh', nn.Tanh())]
        self.fake = nn.Sequential(OrderedDict(layers))

        attn_conv = nn.Conv2d(
            curr_dim, 1, kernel_size=7, stride=1, padding=3, bias=False)
        layers = [('attn', attn_conv)]
        layers += [] if config.image_size <= 256 else [
            ('attn_up_nn_512', nn.Upsample(scale_factor=2, mode='bilinear'))
        ]
        layers += [] if config.image_size <= 512 else [
            ('attn_up_nn_1024', nn.Upsample(scale_factor=2, mode='bilinear'))
        ]
        layers += [('sigmoid', nn.Sigmoid())]
        self.attn = nn.Sequential(OrderedDict(layers))

        if debug and self.Deterministic:
            self.debug()

    def print_debug(self, x, v):
        return _print_debug(x, v, file=self.config.log)

    def debug(self):
        PRINT(self.config.log, '-- Generator:')
        feed = to_var(
            torch.ones(1, self.color_dim, self.image_size, self.image_size),
            volatile=True,
            no_cuda=True)
        features = self.print_debug(feed, self.main)
        self.print_debug(features, self.fake)
        self.print_debug(features, self.attn)

    def forward(self, x):
        features = self.main(x)
        fake_img = self.fake(features)
        mask_img = self.attn(features)
        fake_img = mask_img * x + (1 - mask_img) * fake_img
        output = [fake_img, mask_img]
        return output
