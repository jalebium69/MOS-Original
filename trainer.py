import sys
import logging
import copy
import torch
from utils import factory
from utils.data_manager import DataManager
from utils.toolkit import count_parameters
import os
import numpy as np


def train(args):
    seed_list = copy.deepcopy(args["seed"])
    device = copy.deepcopy(args["device"])

    for seed in seed_list:
        args["seed"] = seed
        args["device"] = device
        _train(args)


def _train(args):
    init_cls = 0 if args["init_cls"] == args["increment"] else args["init_cls"]
    logs_name = "logs/{}/{}/{}/{}".format(args["model_name"], args["dataset"], init_cls, args['increment'])
    
    if not os.path.exists(logs_name):
        os.makedirs(logs_name)

    logfilename = "logs/{}/{}/{}/{}/{}_{}_{}".format(
        args["model_name"],
        args["dataset"],
        init_cls,
        args["increment"],
        args["prefix"],
        args["seed"],
        args["backbone_type"],
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(filename)s] => %(message)s",
        handlers=[
            logging.FileHandler(filename=logfilename + ".log"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    _set_random(args["seed"])
    _set_device(args)
    print_args(args)

    data_manager = DataManager(
        args["dataset"],
        args["shuffle"],
        args["seed"],
        args["init_cls"],
        args["increment"],
        args,
    )
    args["nb_classes"] = data_manager.nb_classes  # update args
    args["nb_tasks"] = data_manager.nb_tasks
    args["class_frequencies"] = data_manager.class_frequencies
    model = factory.get_model(args["model_name"], args)
    imb_metrics=args["imb_metrics"]
    cnn_curve, nme_curve = {"top1": [], "top5": []}, {"top1": [], "top5": []}
    cnn_matrix, nme_matrix = [], []

    # Store curves and matrices for imbalance metrics
    imb_curves = {metric: [] for metric in ["f1_score", "mcc", "kappa", "balanced_accuracy"]}
    imb_matrices = {metric: [] for metric in ["f1_score", "mcc", "kappa", "balanced_accuracy"]}

    for task in range(data_manager.nb_tasks):
        logging.info("All params: {}".format(count_parameters(model._network)))
        logging.info(
            "Trainable params: {}".format(count_parameters(model._network, True))
        )
        model.incremental_train(data_manager)
        cnn_accy, nme_accy = model.eval_task("accuracy")
        model.after_task()

        if nme_accy is not None:
            logging.info("CNN: {}".format(cnn_accy["grouped"]))
            logging.info("NME: {}".format(nme_accy["grouped"]))

            cnn_keys = [key for key in cnn_accy["grouped"].keys() if '-' in key]
            cnn_values = [cnn_accy["grouped"][key] for key in cnn_keys]
            cnn_matrix.append(cnn_values)

            nme_keys = [key for key in nme_accy["grouped"].keys() if '-' in key]
            nme_values = [nme_accy["grouped"][key] for key in nme_keys]
            nme_matrix.append(nme_values)

            cnn_curve["top1"].append(cnn_accy["top1"])
            cnn_curve["top5"].append(cnn_accy["top5"])

            nme_curve["top1"].append(nme_accy["top1"])
            nme_curve["top5"].append(nme_accy["top5"])

            print("\n### CNN Accuracy Results ###")
            print('Average Accuracy (CNN):', sum(cnn_curve["top1"]) / len(cnn_curve["top1"]))
            print('Average Accuracy (NME):', sum(nme_curve["top1"]) / len(nme_curve["top1"]))

            # 🔹 PRINT & STORE IMBALANCE METRICS IF ENABLED 🔹
            if imb_metrics:
                print("\n### Imbalance Metrics ###")
                for metric in ["f1_score", "mcc", "kappa", "balanced_accuracy"]:
                    metric_result = model.eval_task(metric)
                    print(f"{metric.upper()} (CNN):", metric_result[0]["top1"])
                    imb_curves[metric].append( metric_result[0]["top1"])  # Store for averaging
                    if nme_accy is not None:
                        print(f"{metric.upper()} (NME):", metric_result[0]["top1"])

        else:
            logging.info("No NME accuracy.")
            cnn_keys = [key for key in cnn_accy["grouped"].keys() if '-' in key]
            cnn_values = [cnn_accy["grouped"][key] for key in cnn_keys]
            cnn_matrix.append(cnn_values)

            cnn_curve["top1"].append(cnn_accy["top1"])
            cnn_curve["top5"].append(cnn_accy["top5"])

            print("\n### CNN Accuracy Results ###")
            print('Average Accuracy (CNN):', sum(cnn_curve["top1"]) / len(cnn_curve["top1"]))

            # 🔹 PRINT & STORE IMBALANCE METRICS IF ENABLED 🔹
            if imb_metrics:
                print("\n### Imbalance Metrics ###")
                for metric in ["f1_score", "mcc", "kappa", "balanced_accuracy"]:
                    metric_result = model.eval_task(metric)
                    imb_curves[metric].append( metric_result[0]["top1"]) 
                    imb_matrices[metric].append(metric_result[0]["grouped"].values())
                    print(f"Average {metric.upper()} (CNN):", sum(imb_curves[metric])/len(imb_curves[metric]))
                     # Store for averaging

    # 🔹 PRINT ACCURACY MATRIX 🔹
    if len(cnn_matrix) > 0:
        np_acctable = np.zeros([task + 1, task + 1])
        for idxx, line in enumerate(cnn_matrix):
            idxy = len(line)
            np_acctable[idxx, :idxy] = np.array(line)
        np_acctable = np_acctable.T
        print("\n### Accuracy Matrix (CNN) ###")
        print(np_acctable)

    # 🔹 PRINT IMBALANCE METRIC MATRICES 🔹
    if imb_metrics:
        for metric in imb_curves.keys():
            if len(imb_curves[metric]) > 0:
                np_acctable = np.zeros([task + 1, task + 1])
                for idxx, line in enumerate(imb_matrices[metric]):
                    idxy = len(line)
                    np_acctable[idxx, :idxy] = np.array(line)
                np_acctable = np_acctable.T
                print(f"\n### {metric.upper()} Matrix (CNN) ###")
                print(np_acctable)

        # 🔹 PRINT AVERAGE VALUES FOR IMBALANCE METRICS 🔹
        print("\n### Average Imbalance Metrics (CNN) ###")
        for metric, values in imb_curves.items():
            if values:
                avg_value = sum(values) / len(values)
                print(f"Average {metric.upper()} (CNN): {avg_value:.2f}")



def _set_device(args):
    device_type = args["device"]
    gpus = []

    for device in device_type:
        if device == -1:
            device = torch.device("cpu")
        else:
            device = torch.device("cuda:{}".format(device))

        gpus.append(device)

    args["device"] = gpus


def _set_random(seed=1):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def print_args(args):
    for key, value in args.items():
        logging.info("{}: {}".format(key, value))
