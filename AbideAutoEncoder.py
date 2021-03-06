"""

Autoencoders training and fine-tuning.

Usage:
  nn.py [--whole] [--male] [--threshold] [--leave-site-out] [<derivative> ...]
  nn.py (-h | --help)

Options:
  -h --help           Show this screen
  --whole             Run model for the whole dataset
  --male              Run model for male subjects
  --threshold         Run model for thresholded subjects
  --leave-site-out    Prepare data using leave-site-out method
  derivative          Derivatives to process

"""

# https://www.pianshen.com/article/4518318920/
# https://blog.csdn.net/BBJG_001/article/details/104510444
# https://www.cnblogs.com/picassooo/p/12571282.html
# https://www.cnblogs.com/rainsoul/p/11376180.html
# https://www.cnblogs.com/candyRen/p/12113091.html
# https://blog.csdn.net/guyuealian/article/details/88426648
# https://blog.csdn.net/h__ang/article/details/90720579

import torch
import numpy as np
import matplotlib.pyplot as plt
import utils.abide.prepare_utils as PrepareUtils
import utils.functions as functions
import pandas as pd

from docopt import docopt
from torch.utils.data import TensorDataset
from torch.utils.data import DataLoader
from torch import nn, optim
from model.AutoEncoderModel import AutoEncoderModel


if __name__ == '__main__':
    if torch.cuda.is_available():
        gpu_status = True
    else:
        gpu_status = False

    # 模型初始化
    PrepareUtils.reset()

    arguments = docopt(__doc__)

    # 表型数据位置
    pheno_path = './data/ABIDE/phenotypes/Phenotypic_V1_0b_preprocessed1.csv'
    # 载入表型数据
    pheno = PrepareUtils.load_phenotypes(pheno_path)
    # 载入数据集
    hdf5 = PrepareUtils.hdf5_handler(bytes('./data/ABIDE/abide.hdf5', encoding='utf8'), 'a')

    # 脑图谱的选择
    valid_derivatives = ["cc200", "aal", "ez", "ho", "tt", "dosenbach160"]
    derivatives = [derivative for derivative
                   in arguments["<derivative>"]
                   if derivative in valid_derivatives]

    # 标记实现数据
    experiments = []
    for derivative in derivatives:

        config = {"derivative": derivative}

        if arguments["--whole"]:
            experiments += [PrepareUtils.format_config("{derivative}_whole", config)],

        if arguments["--male"]:
            experiments += [PrepareUtils.format_config("{derivative}_male", config)]

        if arguments["--threshold"]:
            experiments += [PrepareUtils.format_config("{derivative}_threshold", config)]

        if arguments["--leave-site-out"]:
            for site in pheno["SITE_ID"].unique():
                site_config = {"site": site}
                experiments += [
                    PrepareUtils.format_config("{derivative}_leavesiteout-{site}",
                                  config, site_config)
                ]

    # 第一个自编码器的隐藏层神经元数量
    code_size_1 = 1000
    # 第二个自编码器的隐藏层神经元数量
    code_size_2 = 600
    # 第一个自编码器的去噪率
    denoising_rate = 0.7
    # 每批数据的大小
    batch_size = 100
    # 自编码器1的学习率
    learning_rate_1 = 0.0001
    # 稀疏参数
    sparse_param = 0.2
    # 稀疏系数
    sparse_coeff = 0.5
    # 训练周期
    EPOCHS = 10
    # 保存训练、验证误差
    train_error = []
    validation_error = []
    test_error = []

    # 定义训练、验证、测试数据
    X_train = y_train = X_valid = y_valid = X_test = y_test = 0

    # 构建自编码器1和自编码器2
    ae_1 = AutoEncoderModel(19900, [1000], 19900, is_denoising=True, denoising_rate=0.7)
    if gpu_status:
        ae_1 = ae_1.cuda()
    # 使用随机梯度下降进行优化
    optimizer_1 = optim.Adam(ae_1.parameters(), lr=learning_rate_1)
    # 使用均方差作为损失函数
    criterion_1 = nn.MSELoss()

    # 要训练的脑图谱列表排序
    experiments = sorted(experiments)
    # 循环训练所有脑图谱
    for experiment_item in experiments:
        # 获得脑图谱名称
        experiment = experiment_item[0]
        # 从HDF5载入实验数据
        exp_storage = hdf5["experiments"][experiment]

        # 循环获得每折数据
        for fold in exp_storage:
            experiment_cv = PrepareUtils.format_config("{experiment}_{fold}", {
                "experiment": experiment,
                "fold": fold,
            })
            # 获取训练数据、验证数据、测试数据
            X_train, y_train, X_valid, y_valid, X_test, y_test = PrepareUtils.load_fold(hdf5["patients"], exp_storage, fold)

            # 保存AE1模型的地址
            ae1_model_path = PrepareUtils.format_config("./data/ABIDE/models/{experiment}_autoencoder-1.ckpt", {
                "experiment": experiment_cv,
            })
            # 保存AE2模型的地址
            ae2_model_path = PrepareUtils.format_config("./data/ABIDE/models/{experiment}_autoencoder-2.ckpt", {
                "experiment": experiment_cv,
            })
            # 保存NN模型的地址
            nn_model_path = PrepareUtils.format_config("./data/ABIDE/models/{experiment}_mlp.ckpt", {
                "experiment": experiment_cv,
            })

            # 创建训练数据集
            train_dataset = TensorDataset(
                torch.from_numpy(X_train).float().clone().detach().requires_grad_(),
                torch.from_numpy(np.array(y_train).reshape(-1, 1)).clone().detach())
            # 创建测试数据集
            test_dataset = TensorDataset(
                torch.from_numpy(X_test).float().clone().detach(),
                torch.from_numpy(np.array(y_test).reshape(-1, 1)).clone().detach())
            # 创建验证数据集
            validation_dataset = TensorDataset(
                torch.from_numpy(X_valid).float().clone().detach(),
                torch.from_numpy(np.array(y_valid).reshape(-1, 1)).clone().detach())

            # 创建训练数据加载器，并且设置每批数据的大小，以及每次读取数据时随机打乱数据
            train_loader = DataLoader(dataset=train_dataset, batch_size=batch_size, shuffle=True)
            # 创建验证集加载器
            validation_loader = DataLoader(dataset=test_dataset, batch_size=batch_size, shuffle=True)
            # 测试集加载器
            test_loader = DataLoader(dataset=validation_dataset, batch_size=batch_size, shuffle=True)

            # 开始训练
            for epoch in range(EPOCHS):
                # 打开反向传播
                ae_1.train()
                # 训练所有数据
                for batch_idx, (data, target) in enumerate(train_loader):
                    if gpu_status:
                        data = data.cuda()
                    # 前向传播，返回编码器和解码器
                    encoder, decoder = ae_1(data)
                    # 获取误差，并添加正则项
                    loss = criterion_1(decoder, data)
                    # 计算KL散度
                    penalty = functions.kl_divergence(encoder.cpu().detach().numpy(), sparse_param, sparse_coeff)
                    loss = loss + penalty
                    # 清空梯度
                    optimizer_1.zero_grad()
                    # 反向传播
                    loss.backward()
                    # 一步随机梯度下降算法
                    optimizer_1.step()
                    # 打印损失值
                    print('Fold {0} Epoch {1} Batch {2} Train Loss: {3}'.format(fold, epoch, batch_idx, loss))
                    train_error.append(loss.cpu())

                    if batch_idx % 5 == 0 and batch_idx != 0:
                        # 关闭反向传播
                        ae_1.eval()
                        # 开始验证所有数据
                        for batch_idx, (data, target) in enumerate(validation_loader):
                            if gpu_status:
                                data = data.cuda()
                            # 前向传播，返回编码器和解码器
                            encoder, decoder = ae_1(data)
                            # 获取误差，并添加正则项
                            loss = criterion_1(decoder, data)
                            # 计算KL散度
                            penalty = functions.kl_divergence(encoder.cpu().detach().numpy(), sparse_param, sparse_coeff)
                            loss = loss + penalty
                            # 打印损失值
                            print('Fold {0} Batch {1} Validation Loss: {2}'.format(fold, batch_idx, loss))
                            validation_error.append(loss.cpu())

            # 关闭反向传播
            ae_1.eval()
            # 开始验证所有数据
            for batch_idx, (data, target) in enumerate(test_loader):
                if gpu_status:
                    data = data.cuda()
                # 前向传播，返回编码器和解码器
                encoder, decoder = ae_1(data)
                # 获取误差，并添加正则项
                loss = criterion_1(decoder, data)
                # 计算KL散度
                penalty = functions.kl_divergence(encoder.cpu().detach().numpy(), sparse_param, sparse_coeff)
                loss = loss + penalty
                # 打印损失值
                print('Fold {0} Batch {1} Test Loss: {2}'.format(fold, batch_idx, loss))
                test_error.append(loss.cpu())

    # 显示损失值
    plt.plot(range(len(train_error)), train_error, label='Train')
    plt.plot(range(len(validation_error)), validation_error, label='Validation')
    plt.plot(range(len(test_error)), test_error, label='Test')
    plt.show()