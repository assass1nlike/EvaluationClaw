import glob
import json
import random
from tqdm import trange
import openai
import os
import time
import re
import random
import numpy
import matplotlib.pyplot as plt
from final_analyze_4 import main_4

def get_answer(s):
    s = s.lower()
    match = re.search(r"answer is ###[^a-zA-Z]*([a-zA-Z])", s)
    if match:
        return match.group(1)
    match = re.search(r"answer:[^a-zA-Z]*([a-zA-Z])", s)
    if match:
        return match.group(1)
    match = re.search(r"###[^a-zA-Z]*([a-zA-Z])", s)
    if match:
        return match.group(1)
    match = re.search(r"[^a-zA-Z]*([a-zA-Z])", s)
    if match:
        return match.group(1)
    return 'None'
def process_sample(sample):
    s = sample.split("Candidates:")
    question = s[0].strip('Question:').strip("\n").strip(" ").strip("\n").strip(" ")
    try:
        s=s[1].split('Right Option:')
    except:
        print(sample)
        return None
    candidates = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
    label = s[1].strip("\n").strip(" ").strip("\n").strip(" ")
    # print(label)
    return {
        'question':question,
        'candiates':candidates,
        'label':label
    }

def process_sample_attr(sample):
    try:
        s = sample.split("Question:")
        analyses = s[0].strip('Analyses:').strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("Candidates:")
        question = s[0].strip('Question:').strip("\n").strip(" ").strip("\n").strip(" ")

        s=s[1].split('Right Option:')
        candidates = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split('Attributes Used:')
        label = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        attributes = s[1].strip("\n").strip(" ").split("##")
        attributes={t.split(":")[0]:t.split(":")[1] for t in attributes}
    # 正则表达式提取 Question、Candidates 和 Right Option
    # print(label)
        if len(label)!=1:
            print(sample)
            return None
    except:
        print(sample)
        return None
    return {
        'analyses':analyses,
        'question':question,
        'candiates':candidates,
        'label':label,
        'attributes':attributes
    }


def draw(data, title):
    bins = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    plt.hist(data, bins=bins, edgecolor='black', alpha=0.7)
    plt.title(title)
    plt.xlabel('Value')
    plt.ylabel('Frequency')
    plt.show()


def process_sample_attr_cot(sample):
    try:
        s = sample.split("Question:")
        analyses = s[0].strip('Analyses:').strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("Reasoning Path:")
        question = s[0].strip('Question:').strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("Candidates:")
        reasoning = s[0].strip('Reasoning Path:').strip("\n").strip(" ").strip("\n").strip(" ")

        s=s[1].split('Right Option:')
        candidates = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split('Attributes Used:')
        label = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("Difficulty Level:")
        attributes = s[0].strip("\n").strip(" ").split("##")
        attributes = {t.split(":")[0]: t.split(":")[1] for t in attributes}
        dif_level = s[1].strip("\n").strip(" ").strip("\n").strip(" ")
        if len(label)!=1:
            return None
    except:
        return None
    return {
        'analyses':analyses,
        'question':question,
        'candiates':candidates,
        'label':label,
        'attributes':attributes,
        'difficulty_level':dif_level,
        'reasoning':reasoning
    }

def process_sample_attr_diffusion(sample):
    try:
        s = sample.split("##Question:##")
        analyses = s[0].strip('##Analyses:##').strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("##Reasoning Path:##")
        question = s[0].strip('Question:').strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("##Candidates:##")
        reasoning = s[0].strip('Reasoning Path:').strip("\n").strip(" ").strip("\n").strip(" ")

        s=s[1].split('##Right Option:##')
        candidates = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split('##Attributes Used:##')
        label = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        attributes = s[1].strip("\n").strip(" ").split("##")
        attributes = {t.split(":")[0]: t.split(":")[1] for t in attributes}
        if len(label)!=1:
            return None
    except:
        return None
    return {
        'analyses':analyses,
        'question':question,
        'candiates':candidates,
        'label':label,
        'attributes':attributes,
        'reasoning':reasoning
    }

def main_2(dataset_name,model,DemoNum,DiverNum,DataSize):
    methods = ['syn']
    demo_num=DemoNum
    can_maps = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
    sub_names = ['attr_deep_diffusion_difattr_diflabel_v2']
    houzhui = "_harder"
    for method in methods:
            for sub_name in sub_names:
                dir_name = "API_Com_{}/{}/{}/{}-{}{}".format(method,dataset_name,model,sub_name,demo_num,houzhui)
                dirs = glob.glob(dir_name+"/raw_data/*")
                if len(dirs)==0:continue
                to_store = 'generated_benchmark/API_Com_{}/{}/{}/{}-{}{}'.format(method, dataset_name, model, sub_name,demo_num,houzhui)
                datas = []
                all_dir_num=0
                dif_list = []
                label_cnt=0
                idx_s = 0
                very_hard = 0
                dif_sub_list = {i:[] for i in range(10)}
                dirs.sort()
                for dir in dirs:
                    subname = dir.split("/")[-1]
                    sub_dirs = glob.glob(dir+"/*")
                    print("{}-{}".format(subname,len(sub_dirs)))
                    all_dir_num+=len(sub_dirs)
                    for sub_dir in sub_dirs:
                        if '.json' not in sub_dir:continue
                        cur_idx = int(sub_dir.split("/")[-1][:-5])
                        if cur_idx>=DataSize:continue
                        try:
                            with open(sub_dir,'r')as f:
                                data = json.load(f)
                                f.close()
                        except:
                            continue
                        data['idx'] = idx_s
                        data['difficulty_idx']=cur_idx
                        data['type'] = [subname]
                        if data['model_predictions'] is not None:
                            rig, cnt = 0, 0
                            pre_list=[]
                            for tt in data['model_predictions']:
                                pre = get_answer(tt)
                                pre_list.append(pre)
                                if pre.lower() == data['label'].lower():
                                    rig += 1
                                cnt += 1
                            dif_level = 1 + 10 * (1 - rig / cnt)
                            dif_sub_list[cur_idx//(DataSize//10)].append(dif_level)
                            dif_list.append(dif_level)
                            data['dif_level'] = dif_level+data['difficulty_idx']/DataSize
                            sc_pre = max(pre_list, key=pre_list.count)
                            if data['label'].lower() != sc_pre.lower():
                                very_hard+=1
                            if data['label'].lower()==data['label']:
                                label_cnt+=1
                        datas.append(data)
                        idx_s+=1
                        # f.close()
                os.makedirs(to_store,exist_ok=True)
                print("data num:{} - {}".format(len(datas),all_dir_num))
                with open(to_store+"/data.json",'w')as f:
                        json.dump(datas,f)
                        f.close()
                print(f"Calibrate Rate:{label_cnt/len(datas):.4f}")
                print(f"Avg Dif Level:{numpy.array(dif_list).mean().item():.3f}")
                print(f"Inconsistent Num:{very_hard}")
                for i in dif_sub_list.keys():
                    print(f"Level {i+1}: {numpy.array(dif_sub_list[i]).mean().item():.3f}")
                # draw(dif_list,"{}#{}#{}".format(dataset_name,model,sub_name))
    avg_dif = (numpy.array(dif_list).mean().item()-1)/10
    to_return = f"Benchmark Size: {len(datas)}\n\nCalibrate Rate: {label_cnt/len(datas):.4f}\n\nAvg Error Rate of {model}: {avg_dif:.3f}\n\n"
    to_return2 = main_4(dataset_name,model,DataSize,DemoNum)
    return to_return+to_return2

def main():
    task_name = 'MMLUPro_My'
    with open("task_des/{}.json".format(task_name),'r')as f:
        task = json.load(f)
        f.close()
    model = task['model']
    dataset_name = task['benchmark_name']
    DataSize = task['NumberPerAbility']
    DemoNum = task['DemoNum']
    DiverNum = task['DiverNum']
    keys = list(task['abilities'].keys())
    main_2(dataset_name,model,DemoNum,DiverNum,DataSize)

if __name__ == "__main__":
    main()