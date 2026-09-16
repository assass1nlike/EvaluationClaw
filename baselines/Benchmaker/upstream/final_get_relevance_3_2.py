import glob
import json
import openai
import os
import time
import random
import re
from API_all import Get

def process_response(sample):
    try:
        s = sample.split("Judgement:")
        analyses = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("Confidence:")
        judgement = s[0]
        matches = re.search(r"[012]", judgement)
        if matches:
            judgement = int(matches[0])
        confidence = s[1]
        matches = re.search(r"[012]", confidence)
        if matches:
            confidence = int(matches[0])
    except:
        # print(sample)
        return None
    return {
        'analyses':analyses,
        'judgement':judgement,
        'confidence':confidence
    }


def main32_raw(dataset_name,generate_model,DemoNum,abilities,judge_model_name='qwen_plus'):
    Mod = Get()
    can_index = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
    prompt = open('rel_prompts/w_reasoning.txt').read()
    sub_name = 'attr_deep_diffusion_difattr_diflabel_v2-{}_harder'.format(DemoNum)
    method = 'syn'
    judge = judge_model_name
    model_name = judge
    dir_name = "generated_benchmark/API_Com_{}/{}/{}/{}/data.json".format(
                        method, dataset_name, generate_model, sub_name)
    if os.path.exists(dir_name):
                    with open(dir_name, 'r') as f:
                        datas = json.load(f)
                        f.close()
                    random.shuffle(datas)
                    further_dir = "generator-{}_method-{}_sub_name-{}_answer-{}".format(generate_model, method, sub_name,
                                                                                        model_name)
                    to_store_dir = "API_Com_REL/{}/{}".format(dataset_name,further_dir)
                    os.makedirs(to_store_dir, exist_ok=True)
                    os.makedirs(to_store_dir + "/raw_data", exist_ok=True)
                    n = 1
                    temp = 0
                    for tem in datas:
                        idx = tem['idx']
                        has_generate = [int(t.split("/")[-1].split(".")[0]) for t in glob.glob(to_store_dir + "/raw_data/*")]
                        if idx in has_generate: continue
                        print(len(has_generate))
                        if True:
                            question = tem['question']+"\nCandidates:\n"+tem['candiates']+"\nGroundTruth:\n"+tem['reasoning']
                            ability = tem['type'][0].split("###")[-1]
                            ability = abilities[ability]
                            cur_prompt=prompt.replace('{{question}}',question).replace('{{ability}}',ability)
                            retry_time = 3
                            while retry_time:
                                try:
                                    response, cost = Mod.calc(cur_prompt, n=n, temp=temp, model=model_name)
                                    response = process_response(response[0])
                                    if response is None:
                                        retry_time -= 1
                                        continue
                                    with open(to_store_dir + "/raw_data/{}.json".format(idx), "w") as f:
                                        cur = {"raw": tem, "response": response}
                                        json.dump(cur, f)
                                        f.close()
                                    break
                                except Exception as e:
                                    print(e)
                                    print("Sleep 10s")
                                    retry_time-=1
                                    time.sleep(10)
    return "Get All Relevance!"

def main32(dataset_name,generate_model,DemoNum,abilities,judge_model_name='qwen_plus'):
    abilities = abilities.to_dict(orient="records")
    abilities = {tem['Name']:tem['Description'] for tem in abilities}
    to_output = main32_raw(dataset_name,generate_model,DemoNum,abilities,judge_model_name)
    return to_output

def main():
    task_name = 'MMLUPro_My_4o'
    with open("task_des/{}.json".format(task_name),'r')as f:
        task = json.load(f)
        f.close()
    abilities = task['abilities']
    model = task['model']
    dataset_name = task['benchmark_name']
    DataSize = task['NumberPerAbility']
    DemoNum = task['DemoNum']
    DiverNum = task['DiverNum']
    main32_raw(dataset_name,model,DemoNum,abilities)

if __name__ == "__main__":
    main()