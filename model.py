import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models

# Pixelwise Cross-entropy loss
class CrossEntropyLoss2d(nn.Module):
    def __init__(self, weight=None, size_average=True):
        super(CrossEntropyLoss2d, self).__init__()
        self.nll_loss = nn.NLLLoss(weight, size_average)

    def forward(self, inputs, targets):
        return self.nll_loss(F.log_softmax(inputs,dim=1), targets)

class DUC(nn.Module):
    def __init__(self, inplanes, planes, upscale_factor=2):
        super(DUC, self).__init__()
        self.relu = nn.ReLU()
        self.conv = nn.Conv2d(inplanes, planes, kernel_size=3,
                              padding=1, bias=True)
        self.bn = nn.BatchNorm2d(planes)
        self.pixel_shuffle = nn.PixelShuffle(upscale_factor)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        x = self.pixel_shuffle(x)
        return x

class upSampleTransposeConv(nn.Module):
    def __init__(self, inplanes, planes, dropout, upscale_factor=2):
        super(upSampleTransposeConv, self).__init__()
        self.relu = nn.ReLU()
        self.conv = nn.ConvTranspose2d(inplanes, planes, kernel_size=3,
                              padding=1, stride=2, output_padding=1, bias=True)
        self.bn = nn.BatchNorm2d(planes)
        self.do = nn.Dropout2d(dropout)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        self.do(x)
        return x

class ConvPool(nn.Module):
    def __init__(self, inplanes, planes, dropout):
        super(ConvPool, self).__init__()
        self.relu = nn.ReLU()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=3, dilation=2,
                              padding=2, bias=False)
        self.pool = nn.Conv2d(planes, planes, kernel_size=3,
                              padding=1, stride=2, bias=False)
        self.bn = nn.BatchNorm2d(planes)
        self.do = nn.Dropout2d(dropout)

    def forward(self, x):
        x = self.conv1(x)
        x = self.relu(x)
        x = self.pool(x)
        x = self.bn(x)
        x = self.relu(x)
        x = self.do(x)
        return x

class ConvPoolDouble(nn.Module):
    def __init__(self, inplanes, planes, dropout):
        super(ConvPoolDouble, self).__init__()
        self.relu = nn.ReLU()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=3, dilation=2,
                              padding=2, bias=False)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, dilation=2,
                              padding=2, bias=False)
        self.pool = nn.Conv2d(planes, planes, kernel_size=3,
                              padding=1, stride=2, bias=False)
        self.bn = nn.BatchNorm2d(planes)
        self.do = nn.Dropout2d(dropout)

    def forward(self, x):
        x = self.conv1(x)
        x = self.relu(x)
        x = self.conv2(x)
        x = self.relu(x)
        x = self.pool(x)
        x = self.bn(x)
        x = self.relu(x)
        x = self.do(x)
        return x

class ConvPoolSimple(nn.Module):
    def __init__(self,inplanes,planes,size,stride,padding,dilation,bias, dropout):
        super(ConvPoolSimple,self).__init__()

        self.conv = nn.Conv2d(inplanes,planes,size,stride=stride,padding=padding,dilation=dilation,bias=bias)
        self.bn = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU()
        self.do = nn.Dropout2d(dropout)

    def forward(self,x):
        x = self.relu(self.bn(self.conv(x)))
        x = self.do(x)
        return x

class Classifier(nn.Module):
    def __init__(self,inplanes,num_classes,poolSize=0,kernelSize=1):
        super(Classifier, self).__init__()
        self.classifier = nn.Conv2d(inplanes,num_classes,kernel_size=kernelSize,padding= kernelSize // 2)
        self.pool = None
        if poolSize > 1:
            self.pool = nn.MaxPool2d(poolSize)

    def forward(self,x):
        if self.pool is not None:
            x = self.pool(x)
        return self.classifier(x)

class PB_FCN(nn.Module):
    def __init__(self,planes, num_classes,kernelSize, noScale,dropout):
        super(PB_FCN, self).__init__()

        self.noScale = noScale

        muliplier = 2 if noScale else 1
        outPlanes = planes//4

        self.FCN = DownSampler(planes, noScale,dropout)

        self.up1 = upSampleTransposeConv(planes*2,planes,dropout)
        self.up2 = upSampleTransposeConv(planes,planes//2*muliplier,dropout)
        self.up3 = upSampleTransposeConv(planes//2*muliplier,outPlanes*muliplier,dropout)
        self.up4 = upSampleTransposeConv(planes//2,outPlanes,dropout) if noScale else None


        self.classifier = Classifier(outPlanes,num_classes,kernelSize=kernelSize)

    def forward(self,x):

        f4, f3, f2, f1, f0 = self.FCN(x)
        if self.noScale:
            x = self.up1(f4) + f3
            x = self.up2(x) + f2
            x = self.up3(x) + f1
            x = self.up4(x) + f0
        else:
            x = self.up1(f3) + f2
            x = self.up2(x) + f1
            x = self.up3(x) + f0

        return self.classifier(x)

class FCN(nn.Module):
    def __init__(self):
        super(FCN,self).__init__()

        planes = 32

        self.FCN = DownSamplerThick(32,0)

        self.up1 = upSampleTransposeConv(planes*2,planes,0)
        self.up2 = upSampleTransposeConv(planes,planes//2,0)
        self.up3 = upSampleTransposeConv(planes//2,planes//2,0)

        self.classifier = Classifier(planes//2,5,1)

    def forward(self,x):
        f3, f2, f1, f0 = self.FCN(x)
        x = self.up1(f3) + f2
        x = self.up2(x) + f1
        x = self.up3(x) + f0
        return self.classifier(x)


class DownSampler(nn.Module):
    def __init__(self,planes, noScale, dropout):
        super(DownSampler, self).__init__()
        self.noScale = noScale
        outPlanes = planes//4

        self.conv0 = ConvPoolSimple(3,outPlanes,3,1,2,2,False,dropout)
        self.conv1 = ConvPoolSimple(outPlanes,planes//2,3,2,1,1,False,dropout)
        self.conv2 = ConvPool(planes//2,planes,dropout)
        self.conv_ext = ConvPool(planes,planes,dropout) if noScale else None
        self.conv3 = ConvPool(planes,planes*2,dropout)
        self.conv4 = ConvPoolSimple(planes*2,planes*4,3,1,2,2,False,dropout*2)
        self.conv5 = ConvPoolSimple(planes*4,planes*4,3,1,2,2,False,dropout*2)
        self.conv6 = ConvPoolSimple(planes*4,planes*4,3,1,2,2,False,dropout*2)
        self.conv7 = ConvPoolSimple(planes*4,planes*4,3,1,2,2,False,dropout*2)
        self.conv8 = ConvPoolSimple(planes*4,planes*2,3,1,2,2,False,dropout*2)

    def forward(self,x):

        x0 = self.conv0(x)
        x1 = self.conv1(x0)
        x2 = self.conv2(x1)
        x3 = self.conv_ext(x2) if self.noScale else self.conv8(self.conv7(self.conv6(self.conv5(self.conv4(self.conv3(x2))))))
        x4 = self.conv8(self.conv7(self.conv6(self.conv5(self.conv4(self.conv3(x3)))))) if self.noScale else None

        return x4, x3, x2, x1, x0

class DownSamplerThick(nn.Module):
    def __init__(self, planes, dropout):
        super(DownSamplerThick, self).__init__()
        outPlanes = planes / 2

        self.conv0 = ConvPoolSimple(3, outPlanes, 3, 1, 2, 2, False, dropout)
        self.conv0_1 = ConvPoolSimple(outPlanes, outPlanes, 3, 1, 2, 2, False, dropout)
        self.conv1 = ConvPoolSimple(outPlanes, outPlanes, 3, 2, 1, 1, False, dropout)
        self.conv2 = ConvPoolDouble(outPlanes, planes, dropout)
        self.conv3 = ConvPoolDouble(planes, planes * 2, dropout)
        self.conv4 = ConvPoolSimple(planes * 2, planes * 4, 3, 1, 2, 2, False, dropout * 2)
        self.conv5 = ConvPoolSimple(planes * 4, planes * 2, 3, 1, 2, 2, False, dropout * 2)

    def forward(self, x):
        x0 = self.conv0_1(self.conv0(x))
        x1 = self.conv1(x0)
        x2 = self.conv2(x1)
        x3 = self.conv5(self.conv4(self.conv3(x2)))

        return x3, x2, x1, x0

class LabelProp(nn.Module):
    def __init__(self,numClass, numPlanes,dropout):
        super(LabelProp,self).__init__()

        self.pre = ConvPoolSimple(8,numPlanes//4,3,1,1,1,False, dropout)
        self.down1 = ConvPoolSimple(numPlanes//4,numPlanes//2,3,2,1,1,False,dropout)
        self.down2 = ConvPoolSimple(numPlanes//2,numPlanes//2,3,2,1,1,False,dropout)
        self.down3 = ConvPoolSimple(numPlanes//2,numPlanes,3,2,1,1,False,dropout)

        self.conv1 = ConvPoolSimple(numPlanes,numPlanes*2,3,1,2,2,False,dropout)
        self.conv2 = ConvPoolSimple(numPlanes*2,numPlanes*2,3,1,2,2,False,dropout)
        self.conv3 = ConvPoolSimple(numPlanes*2,numPlanes,3,1,2,2,False,dropout)

        self.upConv1 = upSampleTransposeConv(numPlanes,numPlanes//2,dropout)
        self.upConv2 = upSampleTransposeConv(numPlanes//2,numPlanes//2,dropout)
        self.upConv3 = upSampleTransposeConv(numPlanes//2,numPlanes//2,dropout)
        self.classifier = nn.Conv2d(numPlanes//2,numClass,1,padding=0)

    def forward(self,x):
        top = self.pre(x)
        middle = self.down1(top)
        bottom = self.down2(middle)
        x = self.down3(bottom)
        x = self.conv3(self.conv2(self.conv1(x)))
        x = bottom + self.upConv1(x)
        x = middle + self.upConv2(x)
        x = self.upConv3(x)
        x[:,0:8,:,:] = x[:,0:8,:,:] + top
        x = self.classifier(x)
        return x

class BNNL(nn.Module):
    def __init__(self):
        super(BNNL,self).__init__()
        self.conv1 = nn.Conv2d(3,8,8,padding=4)
        self.conv2 = nn.Conv2d(8,16,8,padding=3)
        self.conv3 = nn.Conv2d(16,16,8,padding=3)
        self.fc = nn.Conv2d(16,512,1)
        self.classifier = nn.Conv2d(512,4,1)

        self.relu = nn.ReLU()

        self.pool1 = nn.MaxPool2d(4,2)
        self.pool2 = nn.MaxPool2d(4,2)
        self.pool3 = nn.MaxPool2d(4,2)

        self.do1 = nn.Dropout2d(0.25)
        self.do2 = nn.Dropout2d(0.25)
        self.do3 = nn.Dropout2d(0.25)
        self.dof = nn.Dropout(0.5)

    def forward(self,x):
        x = self.relu(self.pool1(self.do1(self.conv1(x))))
        x = self.relu(self.pool2(self.do2(self.conv2(x))))
        x = self.relu(self.pool3(self.do3(self.conv3(x))))
        x = self.classifier(self.relu(self.dof(self.fc(x))))
        return x

class BNNMC(nn.Module):
    def __init__(self):
        super(BNNMC,self).__init__()
        self.conv1 = nn.Conv2d(3,8,5,padding=1)
        self.conv2 = nn.Conv2d(8,16,3,padding=1)
        self.conv3 = nn.Conv2d(16,16,3,padding=1)
        self.classifier = nn.Conv2d(16,4,3)

        self.relu = nn.ReLU()

        self.pool1 = nn.MaxPool2d(4,2)
        self.pool2 = nn.MaxPool2d(4,2)
        self.pool3 = nn.MaxPool2d(2,2)

        self.do1 = nn.Dropout2d(0.25)
        self.do2 = nn.Dropout2d(0.25)
        self.do3 = nn.Dropout2d(0.25)

    def forward(self,x):
        x = self.relu(self.pool1(self.do1(self.conv1(x))))
        x = self.relu(self.pool2(self.do2(self.conv2(x))))
        x = self.relu(self.pool3(self.do3(self.conv3(x))))
        x = self.classifier(x)
        return x


def loadModel(model,noScale,deep,fineTune,prune,mapLoc):
    path = "./pth/bestModel" + ("Seg" if fineTune else "") + ("VGA" if noScale else "") + ("Deep" if deep else "") + ("Finetuned" if prune else "") + ".pth"
    if fineTune:
        stateDict = torch.load(path, map_location=mapLoc)
        model.load_state_dict(stateDict)
    else:
        if deep:
            return
        else:
            stateDict = torch.load(path, map_location=mapLoc)
            model.FCN.load_state_dict(stateDict)

def pruneModel(params, lower = 73, upper = 77):
    i = 0
    indices = []
    for param in params:
        if param.dim() > 1:
            param = param.data
            thresh = param.std()
            while True:
                num = float(torch.sum(torch.abs(param) < thresh)) / float(torch.sum(param != 0)) * 100
                if num < lower:
                    thresh *= 1.025
                elif num > upper:
                    thresh *= 0.975
                else:
                    break
            print("Pruned %f%% of the weights" % (
            float(torch.sum(torch.abs(param) < thresh)) / float(torch.sum(param != 0)) * 100))
            param[torch.abs(param) < thresh] = 0
            indices.append(torch.abs(param) < thresh)
            i += 1

    return indices
