import glob
import json
import openai
import os
import time
import random
from API_all import Get

def main31(dataset_name,generate_model,DemoNum,judge_model_name = 'qwen_plus'):
    Mod = Get()
    can_index = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
    prompt_name = 'w_reasoning_2'
    prompt = open('ana_prompts/{}.txt'.format(prompt_name)).read()
    sub_name = 'attr_deep_diffusion_difattr_diflabel_v2-{}_harder'.format(DemoNum)
    method = 'syn'
    judge = judge_model_name
    model_name = judge
    dir_name = "generated_benchmark/API_Com_{}/{}/{}/{}/data.json".format(method, dataset_name, generate_model, sub_name)
    if os.path.exists(dir_name):
                        with open(dir_name, 'r') as f:
                            datas = json.load(f)
                            f.close()
                        random.shuffle(datas)
                        further_dir = "generator-{}_method-{}_sub_name-{}_answer-{}_{}".format(generate_model, method, sub_name,
                                                                                            model_name,prompt_name)
                        to_store_dir = "API_Com_GPT_judge_v3/{}/{}".format(dataset_name,further_dir)
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
                                question = tem['question']+"\nCandidates:\n"+tem['candiates']
                                cur_prompt=prompt.replace('{{question}}',question).replace('{{response}}',tem['reasoning']+"\nThe answer is {}".format(tem['label']))
                                while True:
                                    try:
                                        response, cost = Mod.calc(cur_prompt, n=n, temp=temp, model=model_name)
                                        with open(to_store_dir + "/raw_data/{}.json".format(idx), "w") as f:
                                            cur = {"raw": tem, "response": response}
                                            print(response[0])
                                            print("###########\n\n")
                                            json.dump(cur, f)
                                            f.close()
                                        break
                                    except Exception as e:
                                        print(e)
                                        print("Sleep 10s")
                                        time.sleep(10)
    return "Get All Faithfulness!"

def main():
    task_name = 'MMLUPro_My_4o'
    with open("task_des/{}.json".format(task_name),'r')as f:
        task = json.load(f)
        f.close()
    model = task['model']
    dataset_name = task['benchmark_name']
    DataSize = task['NumberPerAbility']
    DemoNum = task['DemoNum']
    DiverNum = task['DiverNum']
    main31(dataset_name,model,DemoNum)

if __name__ == "__main__":
    main()