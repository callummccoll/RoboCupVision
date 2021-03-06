import torch
from torch.autograd import Variable
from torch.utils import data
from model import DownSampler, Classifier, BNNL, BNNMC
import lr_scheduler
from visualize import LinePlotter
from torchvision.transforms import Compose, Normalize, ToTensor, RandomHorizontalFlip, ColorJitter
from transform import ToYUV
import torchvision.datasets as datasets
import progressbar
import numpy as np
import argparse


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--hessL", help="Use BNN-L from Hess et. al.",
                        action="store_true")
    parser.add_argument("--hessMC", help="Use BNN-M-C from Hess et. al.",
                        action="store_true")
    args = parser.parse_args()
    hessL = args.hessL
    hessMC = args.hessMC
    if not hessMC: hessL = True

    input_transform = Compose([
        ToYUV(),
        ToTensor(),
        Normalize([.5, 0, 0], [.5, .5, .5]),

    ])

    input_transform_tr = Compose([
        RandomHorizontalFlip(),
        ColorJitter(brightness=0.5,contrast=0.5,saturation=0.4,hue=0.3),
        ToYUV(),
        ToTensor(),
        Normalize([.5, 0, 0], [.5, .5, .5]),

    ])

    seed = 12345678
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)

    batchSize = 64

    trainDataRoot = "./data/Classification/correctBBsTrain/"

    trainloader = data.DataLoader(datasets.ImageFolder(trainDataRoot, transform=input_transform_tr),
                                  batch_size=batchSize, shuffle=True, num_workers=4)

    valloader = data.DataLoader(datasets.ImageFolder("./data/Classification/correctBBs", transform=input_transform),
                                  batch_size=batchSize, shuffle=True, num_workers=4)

    numClass = 4
    modelHess = BNNL()
    if hessMC:
        modelHess = BNNMC()
    weights = torch.ones(numClass)
    if torch.cuda.is_available():
        modelHess = modelHess.cuda()
        weights = weights.cuda()

    criterion = torch.nn.CrossEntropyLoss(weights)

    mapLoc = None if torch.cuda.is_available() else {'cuda:0': 'cpu'}

    epochs = 40
    lr = 1e-2
    weight_decay = 5e-4
    momentum = 0.9


    def cb():
        print("Best Model reloaded")
        if hessMC:
            stateDict = torch.load("./pth/bestModelHessMC" + ".pth",
                                   map_location=mapLoc)
            modelHess.load_state_dict(stateDict)
        elif hessL:
            stateDict = torch.load("./pth/bestModelHessL" + ".pth",
                                   map_location=mapLoc)
            modelHess.load_state_dict(stateDict)

    optimizer = torch.optim.SGD( [
                                    { 'params': modelHess.parameters()}, ],
                                 lr=lr, momentum=momentum, weight_decay=weight_decay )
    scheduler = lr_scheduler.ReduceLROnPlateau(optimizer,'min',factor=0.2,patience=10,verbose=True,threshold=1e-3,cb=cb)

    ploter = LinePlotter()

    bestLoss = 100
    bestAcc = 0
    bestTest = 0

    for epoch in range(epochs):

        modelHess.train()
        running_loss = 0.0
        running_acc = 0.0
        imgCnt = 0
        conf = torch.zeros(numClass,numClass).long()
        bar = progressbar.ProgressBar(0,len(trainloader),redirect_stdout=False)
        for i, (images, labels) in enumerate(trainloader):
            if torch.cuda.is_available():
                images = images.cuda()
                labels = labels.cuda()

            optimizer.zero_grad()

            pred = torch.squeeze(modelHess(images))
            loss = criterion(pred,labels)

            loss.backward()
            optimizer.step()

            bSize = images.size()[0]
            imgCnt += bSize

            running_loss += loss.item()
            _, predClass = torch.max(pred, 1)
            running_acc += torch.sum( predClass == labels ).item()*100

            for j in range(bSize):
                conf[(predClass[j],labels[j])] += 1

            bar.update(i)

        bar.finish()
        print("Epoch [%d] Training Loss: %.4f Training Acc: %.2f" % (epoch+1, running_loss/(i+1), running_acc/(imgCnt)))
        #ploter.plot("loss", "train", epoch+1, running_loss/(i+1))

        running_loss = 0.0
        running_acc = 0.0
        imgCnt = 0
        conf = torch.zeros(numClass,numClass).long()
        modelHess.eval()
        bar = progressbar.ProgressBar(0, len(valloader), redirect_stdout=False)
        for i, (images, labels) in enumerate(valloader):
            if torch.cuda.is_available():
                images = images.cuda()
                labels = labels.cuda()

            pred = torch.squeeze(modelHess(images))
            loss = criterion(pred, labels)

            bSize = images.size()[0]
            imgCnt += bSize

            running_loss += loss.item()
            _, predClass = torch.max(pred, 1)
            running_acc += torch.sum(predClass == labels).item()*100

            for j in range(bSize):
                conf[(predClass[j],labels[j])] += 1

            bar.update(i)

        bar.finish()
        print("Epoch [%d] Validation Loss: %.4f Validation Acc: %.2f" % (epoch+1, running_loss/(i+1), running_acc/(imgCnt)))
        #ploter.plot("loss", "val", epoch+1, running_loss/(i+1))

        if bestAcc < running_acc/(imgCnt):
            bestLoss = running_loss/(i+1)
            bestAcc = running_acc/(imgCnt)
            bestConf = conf
            total = torch.sum(bestConf[:,1:4]).item()
            totAcc = bestConf[1,1]+bestConf[2,2]+bestConf[3,3]
            fp = torch.sum(bestConf[1:4,:]).item()-totAcc
            print(conf)
            if hessL:
                torch.save(modelHess.state_dict(), "./pth/bestModelHessL" + ".pth")
            elif hessMC:
                torch.save(modelHess.state_dict(), "./pth/bestModelHessMC" + ".pth")
            print("Best: Accuracy: %.4f False Neg: %.2f False Pos: %.2f" % (totAcc/total*100, 100-totAcc/total*100, fp/total*100))

        scheduler.step(running_loss/(i+1))

    print("Finished: Best Validation Loss: %.4f Best Validation Acc: %.2f" % (bestLoss, bestAcc))

    total = torch.sum(bestConf[:,1:4]).item()
    totAcc = bestConf[1,1]+bestConf[2,2]+bestConf[3,3]
    fp = torch.sum(bestConf[1:4,:]).item()-totAcc

    print("Finished: Accuracy: %.4f False Neg: %.2f False Pos: %.2f" % (totAcc/total*100, 100-totAcc/total*100, fp/total*100))

