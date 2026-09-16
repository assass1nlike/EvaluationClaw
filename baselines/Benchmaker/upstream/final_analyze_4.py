import glob
import json
import os
import random
from final_utils import *
import numpy as np
import nltk
from nltk.tokenize import word_tokenize
from collections import Counter
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from nltk.corpus import stopwords


def main_4(dataset_name,generate_model,DataSize,DemoNum):
    to_output = ""
    judge = "qwen_plus"
    # sub_name = 'attr_human_v2'
    sub_name = 'attr_deep_diffusion_difattr_diflabel_v2-{}_harder'.format(DemoNum)
    method = 'syn'

    with open("generated_benchmark/API_Com_syn/{}/{}/{}/data.json".format(dataset_name,generate_model,sub_name),'r')as f:
        data=json.load(f)
        f.close()

    ### lexical
    # samples = [tem['question']+"\n"+tem['candiates'] for tem in data]
    samples = [tem['question'] for tem in data]
    # result = calculate_shannon_entropy(samples)
    gram_2 = process_texts(samples)

    tokens = []
    for string in samples:
        tokens.extend(word_tokenize(string.lower()))  # 将字符串转为小写并分词
    stop_words = set(stopwords.words())
    stop_words = stop_words.union(set(['--','considering','data','system']))
    tokens = [word for word in tokens if word not in stop_words]
    tokens = [word for word in tokens if len(word)>2]
    word_counts = Counter(tokens)
    import numpy as np
    word_counts_smoothed = {word: count for word, count in word_counts.items()}  # 取平方根

    # word_counts_smoothed = {word: np.log1p(count) for word, count in word_counts.items()}  # log(1+x) 避免log(0)问题
    wordcloud = WordCloud(width=1600, height=900, background_color="white",colormap="twilight").generate_from_frequencies(word_counts_smoothed)
    plt.figure(figsize=(16, 9))
    plt.imshow(wordcloud, interpolation="bilinear")
    plt.axis("off")
    plt.savefig("generated_benchmark/API_Com_syn/{}/{}/{}/wordfig.jpg".format(dataset_name,generate_model,sub_name), dpi=300)
    result = calculate_shannon_entropy(samples)
    to_output+=f"Lexical - Entropy: {result['Entropy']:.4f}\n\n"
    print(f"Entropy: {result['Entropy']:.4f}")
    to_output+=f"Lexical - 2-gram: {gram_2:.4f}\n\n"
    print(f"2-gram: {gram_2:.4f}")
    to_output += f"Avg Length: {result['AvgLen']:.4f}\n\n"
    print(f"Avg Length: {result['AvgLen']:.4f}")

    ### Semantic
    if os.path.exists('API_Com_syn/{}/{}/{}/embed'.format(dataset_name, generate_model, sub_name)):
        dirs = glob.glob('API_Com_syn/{}/{}/{}/embed/*/*.json'.format(dataset_name, generate_model, sub_name))
        cur_emb = []
        for dir in dirs:
            try:
                with open(dir, 'r') as f:
                    tem = json.load(f)
                    f.close()
                cur_emb.append(tem['embedding'])
            except:
                pass
        cur_emb = np.array(cur_emb)
        diversity = calculate_diversity(cur_emb)
        to_output += f"Semantic - EuclideanDis: {diversity:.4f}\n\n"
        print(f"Semantic - EuclideanDis: {diversity:.4f}")
    elif os.path.exists('generated_benchmark/API_Com_syn/{}/{}/{}/embedding.json'.format(dataset_name,generate_model,sub_name)):
        with open('generated_benchmark/API_Com_syn/{}/{}/{}/embedding.json'.format(dataset_name,generate_model,sub_name),
                  'r') as f:
            cur_emb = json.load(f)
            random.shuffle(cur_emb)
            # cur_emb = cur_emb[:min(len(cur_emb),len(human_emb))]
            cur_emb_ = []
            for t in cur_emb:
                if t['embedding'] is not None:
                    cur_emb_.append(t['embedding'])
            cur_emb = np.array(cur_emb_)
            f.close()
        diversity = calculate_diversity(cur_emb)
        to_output += f"Semantic - EuclideanDis: {diversity:.4f}\n\n"
        print(f"Semantic - EuclideanDis: {diversity:.4f}")
    else:
        to_output += f"Semantic - EuclideanDis: No Data\n\n"
        print(f"Semantic - EuclideanDis: No Data")


    ### faithfulness
    base_strategy = 'noattr_nodeep-8'
    further_dir = "generator-{}_method-{}_sub_name-{}_answer-{}_w_reasoning_2".format(generate_model, method, sub_name,judge)
    to_store_dir = "API_Com_GPT_judge_v3/{}/{}/raw_data/*".format(dataset_name, further_dir)
    dirs = glob.glob(to_store_dir)
    data_records_cur = []
    fai_cnt,all_cnt = 0,1e-8
    for dir in dirs:
        try:
            with open(dir,'r')as f:
                data = json.load(f)
                f.close()
            data = process_fai_response(data["response"][0])
            if data is not None:
                score = int(data['judgement'])
                if score == 2:score=1
                data_records_cur.append({
                    'strategy': sub_name,
                    'judge_length': len(data['analyses'].split(" ")),
                    'judge_correctness': score
                })
                fai_cnt+=score
                all_cnt+=1
        except:
            pass
    if all_cnt>1:
        to_output += f"Biased Faithfulness: {fai_cnt/all_cnt:.4f}\n\n"
        print(f"Biased Faithfulness: {fai_cnt/all_cnt:.4f}")
    else:
        to_output += f"Biased Faithfulness: No Data\n\n"
        print(f"Biased Faithfulness: No Data")


    ### relevance
    further_dir = "generator-{}_method-{}_sub_name-{}_answer-{}".format(generate_model, method, sub_name,
                                                                        judge)
    dirs = glob.glob("API_Com_REL/{}/{}/raw_data/*".format(dataset_name, further_dir))
    print(len(dirs))
    datas = []
    for dir in dirs:
            try:
                with open(dir, 'r') as f:
                    t = json.load(f)
                    datas.append(t)
                    f.close()
            except:
                print(dir)
                pass
    rels, cons = [], []
    for tem in datas:
        try:
            rele = int(tem["response"]['judgement'])
            conf = int(tem["response"]['confidence'])
            rels.append(rele/2)
            cons.append(conf)
        except:
            pass
    if len(rels)>0:
        to_output += f"Biased Relevance: {np.array(rels).mean().item():.4f}\n\n"
        print(f"Biased Relevance: {np.array(rels).mean().item():.4f}")
    else:
        to_output += f"Biased Relevance: No Data\n\n"
        print(f"Biased Relevance: No Data")

    return to_output





def main():
    task_name = 'MMLUPro_My_4o'
    with open("task_des/{}.json".format(task_name),'r')as f:
        task = json.load(f)
        f.close()
    model = task['model']
    generate_model = model
    dataset_name = task['benchmark_name']
    DataSize = task['NumberPerAbility']
    DemoNum = task['DemoNum']
    DiverNum = task['DiverNum']
    keys = list(task['abilities'].keys())
    main_4(dataset_name,model,DataSize,DemoNum)

if __name__ == "__main__":
    main()
