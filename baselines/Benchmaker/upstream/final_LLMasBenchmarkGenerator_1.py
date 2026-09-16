import glob
import json
import random
from tqdm import trange
from API_all import Get
import openai
import os
import time
import re
import random
import argparse
from copy import deepcopy
from utils import *
from filelock import FileLock
def get_faith(s):
    s = s.lower()
    matches = re.findall(r'###(.*?)###', s)
    if matches:
        try:
            faith =  int(matches[-1].split(":")[1].strip(""))
        except:
            faith = 0
    else:
        faith = 0
    matches = re.findall(r'!!!(.*?)!!!', s)
    if matches:
        try:
            label =  matches[-1].split(":")[1].strip("").strip()
        except:
            label = 'None'
    else:
        label = 'None'
        faith = 0
    return faith,label

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
            # print(sample)
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





def main_1_single(model,ability_des,dataset_name,ability,DataSize,DemoNum,DiverNum,OptionNum):
    method = 'attr_deep_diffusion_difattr_diflabel_v2'
    demo_num = DemoNum
    dir_name = "API_Com_syn/{}/{}/{}-{}_harder".format(dataset_name,model,method,demo_num)
    dir_name_ = "API_Com_syn/{}/{}/{}".format(dataset_name,model,'attr')
    n=1
    temp=1
    sample_num = DataSize
    diver_num = DiverNum
    os.makedirs(dir_name + "/raw_data", exist_ok=True)
    os.makedirs(dir_name + "/failed_data", exist_ok=True)
    chosen_major_subject = dataset_name#['Engineering','Medicine','Economics','Management Studies','History']#['Reasoning']#['Mathematics']
    prompt = open('prompts/syn_{}.txt'.format(method)).read()
    judge_cmp_prompt = open('prompts/judge_cmp.txt').read()
    Mod = Get()
    cans = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
    OptionDemo = ""
    for i in range(OptionNum):
        OptionDemo+="{}. {{{{Option {}}}}}\n".format(cans[i],i)
    prompt=prompt.replace("{{CandidatesDemo}}",OptionDemo).replace("{{OptionNum}}",str(OptionNum))

    for major_subject in [chosen_major_subject]:
        cur_subject = [major_subject]
        for subject in cur_subject:
            cur_key = [ability]
            for keykey in cur_key:
                try:
                    with open(dir_name_ + "/raw_data/{}###{}###{}/attrs/attr1.json".format(major_subject, subject, keykey),
                              "r") as f:
                        attr1 = json.load(f)
                        f.close()
                except:
                    print(
                        "!!!Not Found:  " + dir_name_ + "/raw_data/{}###{}###{}/attrs/attr1.json".format(major_subject,
                                                                                                         subject,
                                                                                                         keykey))
                    continue
                try:
                    with open(dir_name_ + "/raw_data/{}###{}###{}/attrs/attr2.json".format(major_subject, subject, keykey),
                              "r") as f:
                        attr2 = json.load(f)
                        f.close()
                except:
                    print(
                        "!!!Not Found:  " + dir_name_ + "/raw_data/{}###{}###{}/attrs/attr2.json".format(major_subject,
                                                                                                         subject,
                                                                                                         keykey))
                    continue
                try:
                    with open(dir_name_ + "/raw_data/{}###{}###{}/attrs/attr3.json".format(major_subject, subject, keykey),
                              "r") as f:
                        attr4 = json.load(f)
                        f.close()
                except:
                    print("!!!Not Found:  "+dir_name_ + "/raw_data/{}###{}###{}/attrs/attr3.json".format(major_subject, subject, keykey))
                    continue

                dif_bank = [[{},1]]
                for key_ in attr4.keys():
                    dif_bank_new = []
                    for t in attr4[key_]:
                        for cand in dif_bank:
                            new_cand = deepcopy(cand)
                            new_cand[1]=new_cand[1]+t[1]
                            new_cand[0][key_]=t[0]
                            dif_bank_new.append(new_cand)
                    dif_bank=dif_bank_new
                dif_bank = sorted(dif_bank,key=lambda x:x[1])
                dif_bank=[t[0] for t in dif_bank]
                dif_bank = dif_bank[len(dif_bank)//2:]
                dif_banks=[]
                for i in range(10):
                    dif_banks.append(dif_bank[int(i/10*len(dif_bank)):int((i+1)/10*len(dif_bank))])

                for tem in attr2:
                    if tem['attribute'] == 'Difficulty':
                        difficulty_set = tem['values']
                c_dir = dir_name + "/raw_data/{}###{}###{}".format(major_subject, subject, keykey)
                cnt_dir = dir_name + "/{}###{}###{}_count.json".format(major_subject, subject, keykey)
                dif_dir = dir_name + "/dif/{}###{}###{}".format(major_subject, subject, keykey)
                c_fail_dir = dir_name + "/failed_data/{}###{}###{}".format(major_subject, subject, keykey)
                os.makedirs(c_dir, exist_ok=True)
                os.makedirs(dif_dir, exist_ok=True)
                os.makedirs(c_fail_dir, exist_ok=True)
                mid_idx = 0
                if not os.path.exists(cnt_dir):
                    with open(cnt_dir,"w")as f:
                        ttt={}
                        json.dump(ttt,f)
                        f.close()
                repeat_time = DataSize*3
                while True:
                    if repeat_time<=0:break
                    repeat_time-=1
                    begin_direction = 1
                    cur_nums = []
                    for t in glob.glob(c_dir + "/*"):
                        if '.json' not in t:continue
                        cur_nums.append(int(t.split("/")[-1].split(".")[0]))
                    print(len(cur_nums))
                    if len(cur_nums)>=sample_num:break
                    if len(cur_nums)==0:cur_idx = mid_idx
                    else:
                        cur_nums.sort()
                        cur_idx = cur_nums[-1] + 1 if begin_direction==1 else cur_nums[0] -1
                        if cur_idx>=sample_num or cur_idx<0:continue
                    with open(c_dir + "/{}.json".format(cur_idx),'w')as f:
                        f.close()
                    qujian = int(cur_idx/sample_num*10)
                    demo_samples = []
                    with open(cnt_dir, "r")as f:
                        cnt_log = json.load(f)
                        f.close()
                    dif_dict = [tt.split("/")[-1][:-5] for tt in glob.glob("{}/*.json".format(dif_dir))]
                    dif_dict = {int(tt.split("-")[0]):float(tt.split("-")[1]) for tt in dif_dict}
                    for key in dif_dict.keys():
                        if str(key) in cnt_log.keys():
                            dif_dict[key] *= pow(0.9,cnt_log[str(key)]*4/demo_num)
                    dif_dict = [[key,dif_dict[key]] for key in dif_dict.keys()]
                    dif_dict = sorted(dif_dict,key=lambda x:x[1], reverse=True)
                    dif_list = [dif_dict[iii][0] for iii in range(min(len(dif_dict),2*demo_num))]
                    random.shuffle(dif_list)
                    for iii in dif_list:
                        try:
                            with open(c_dir + "/{}.json".format(iii), 'r') as f:
                                pre_data = json.load(f)
                                f.close()
                            pre_data = "##Question:##\n" + pre_data['question'] + "\n" + "##Candidates:##\n" + pre_data[
                                'candiates'] + "\n##Right Option:## " + pre_data['label'] + "\n\n"
                            demo_samples.append(pre_data)
                            if str(iii) not in cnt_log.keys():
                                cnt_log[str(iii)] = 0
                            cnt_log[str(iii)] += 1
                            if len(demo_samples)==demo_num:break
                        except:
                            pass

                    lock = FileLock(f"{cnt_dir}.lock")
                    with lock:
                        with open(cnt_dir, "w")as f:
                            json.dump(cnt_log,f)
                            f.close()
                    print("Demo Num:{}".format(len(demo_samples)))
                    find_sample = False
                    while not find_sample:
                        random.shuffle(demo_samples)
                        demo_samples = ["Example {}:\n".format(j+1)+demo_samples[j] for j in range(len(demo_samples))]
                        cur_prompt = prompt.replace('{{original task}}',ability_des)
                        cur_prompt=cur_prompt.replace('{{task define}}', attr1['task']).replace('{{query define}}', attr1['query']).replace('{{option define}}', attr1['option'])
                        cur_attribute = ""
                        att_list = {}
                        for tem in attr2:
                            if tem['attribute'] == 'Difficulty':
                                continue
                            value = random.choice(tem['values'])
                            cur_attribute+="{}:{}\n".format(tem['attribute'],value)
                            att_list[tem['attribute']]=value
                        dif_att_list={}
                        dif_attr=""
                        cur_dif_attr = random.choice(dif_banks[qujian])
                        for tem in cur_dif_attr.keys():
                            dif_attr += "{}:{}\n".format(tem,cur_dif_attr[tem])
                            dif_att_list[tem]=cur_dif_attr[tem]
                        cur_prompt =cur_prompt.replace('{{attribute define}}', cur_attribute[:-1]).replace('{{difficulty attribute define}}', dif_attr[:-1])
                        cur_prompt = cur_prompt.replace('{{difficulty direction}}', 'higher' if begin_direction == 1 else 'lower')
                        cur_demos = "\n".join(demo_samples)
                        cur_prompt = cur_prompt.replace('{{demonstrations}}',cur_demos)
                        while True:
                            try:
                                response, cost = Mod.calc(cur_prompt, n=diver_num, temp=temp, model=model)
                                break
                            except Exception as e:
                                print(e)
                                print("Sleep 10s")
                                time.sleep(10)
                        if_flag = 1
                        sample_cands = []
                        for tttt in response:
                            cur_rep = process_sample_attr_diffusion(tttt)
                            if cur_rep is None:continue
                            if_flag = 0
                            sample_cands.append(cur_rep)
                        if if_flag:continue
                        sample_cands_list = ["##Question:##\n" + pre_data['question'] + "\n" + "##Candidates:##\n" + pre_data[
                                'candiates'] + "\n##Right Option:## " + pre_data['label'] + "\n\n" for pre_data in sample_cands]
                        cand_idx = calculate_shannon_entropy_batch(demo_samples,sample_cands_list)
                        sample_cand = sample_cands[cand_idx]
                        print(sample_cand['question']+"\n"+sample_cand['candiates'])

                        ### SC
                        raw_prompt = 'You are an expert exceiling at answering difficult questions. Please analyse and think the question and candidate options below step by step and then give your option in template "My answer is ###option###". (Example: My answer is ###E###)\n\nQuestion:'
                        cur_prompt_sc = raw_prompt + sample_cand['question'] + "\nCandidates:\n" + sample_cand['candiates'] + "\n"
                        while True:
                            try:
                                response, cost = Mod.calc(cur_prompt_sc, n=10, temp=1, model='4omini')
                                break
                            except Exception as e:
                                print(e)
                                print("Sleep 10s")
                                time.sleep(10)
                        pre_list = []
                        total_rig,total_cnt=0,0
                        pre_dict = {}
                        for s in response:
                            try:
                                pre = get_answer(s)
                            except:
                                pre = "None"
                            if pre is None: pre = "None"
                            if pre not in pre_dict.keys():
                                pre_dict[pre.lower()] = []
                            pre_dict[pre.lower()].append(s)
                            pre_list.append(pre.lower())
                            total_rig += sample_cand['label'].lower() == pre.lower()
                            total_cnt += 1
                        sc_pre = max(pre_list, key=pre_list.count)
                        dif_level = 1+10 * (1 - total_rig / total_cnt)
                        sample_cand['dif_level'] = dif_level
                        sample_cand['model_predictions'] = response
                        sample_cand['sc_pre'] = sc_pre

                        ### faithfullness
                        if sc_pre != sample_cand['label'].lower():
                            try:
                                cur_prompt = judge_cmp_prompt.replace("{{question}}",sample_cand['question'] + "\nCandidates:\n" + sample_cand['candiates'] + "\n")
                            except:
                                continue
                            cur_prompt1 = cur_prompt.replace('{{can1}}',random.choice(pre_dict[sc_pre])).replace('{{can2}}',sample_cand['reasoning'])
                            cur_prompt2 = cur_prompt.replace('{{can2}}', random.choice(pre_dict[sc_pre])).replace('{{can1}}',
                                                                                                   sample_cand['reasoning'])
                            while True:
                                try:
                                    judge_response1, cost = Mod.calc(cur_prompt1, n=1, temp=0, model=model)
                                    break
                                except Exception as e:
                                    print(e)
                                    print("Sleep 10s")
                                    time.sleep(10)
                            faith1,label1 = get_faith(judge_response1[0])
                            if faith1!=2:
                                sample_cand['faith'] = faith1
                                sample_cand['reason'] = judge_response1[0]
                                with open("{}/{}.json".format(c_fail_dir, str(cur_idx)+"-"+str(random.randint(0,200))), "w") as f:
                                    sample_cand['attribute'] = att_list
                                    sample_cand["dif_attrbute"] = dif_att_list
                                    json.dump(sample_cand, f)
                                    f.close()
                                continue
                            while True:
                                try:
                                    judge_response2, cost = Mod.calc(cur_prompt1, n=1, temp=0, model=model)
                                    print(response[0])
                                    break
                                except Exception as e:
                                    print(e)
                                    print("Sleep 10s")
                                    time.sleep(10)
                            faith2, label2 = get_faith(judge_response2[0])
                            if faith2!=2:
                                sample_cand['faith'] = faith2
                                sample_cand['reason'] = judge_response2[0]
                                with open("{}/{}.json".format(c_fail_dir, str(cur_idx)+"-"+str(random.randint(0,200))), "w") as f:
                                    sample_cand['attribute'] = att_list
                                    sample_cand["dif_attrbute"] = dif_att_list
                                    json.dump(sample_cand, f)
                                    f.close()
                                continue
                            if  label2!=label1:
                                sample_cand['faith'] = 2
                                sample_cand['reason'] = "not consistency"
                                with open("{}/{}.json".format(c_fail_dir, str(cur_idx)+"-"+str(random.randint(0,200))), "w") as f:
                                    sample_cand['attribute'] = att_list
                                    sample_cand["dif_attrbute"] = dif_att_list
                                    json.dump(sample_cand, f)
                                    f.close()
                                continue
                            sample_cand['label'] = label1
                            all_rig,all_cnt=0,0
                            for tt in sample_cand['model_predictions']:
                                if sample_cand['label'].lower()==get_answer(tt).lower():
                                    all_rig+=1
                                all_cnt+=1
                            dif_level = 1 + 10 * (1 - all_rig / all_cnt)
                            sample_cand['dif_level'] = dif_level
                        with open("{}/{}.json".format(c_dir, cur_idx), "w") as f:
                            sample_cand['attribute'] = att_list
                            sample_cand["dif_attrbute"] = dif_att_list
                            json.dump(sample_cand, f)
                            f.close()
                        with open("{}/{}.json".format(dif_dir, f"{cur_idx}-{sample_cand['dif_level']:.2f}"), "w") as f:
                            f.close()
                        find_sample=True
    all_dirs = glob.glob(c_dir + "/*.json")
    to_output = ""
    idx = 1
    for t in all_dirs[-min(len(all_dirs),5):]:
        if '.json' not in t: continue
        with open(t,"r")as f:
            data = json.load(f)
            f.close()
        to_output+="## Example {}\n".format(idx)
        idx+=1
        to_output += "#### Question:\n{}\nOptions:\n{}\nReasoning Path:\n{}\nLabel:\n{}\n\n".format(data['question'],data['candiates'],data['reasoning'],data['label'].upper())
    return to_output

def main_1(model,abilities_df,dataset_name,DataSize,DemoNum,DiverNum,OptionNum):
    abilities = abilities_df.to_dict(orient="records")
    to_print = ""
    for tem in abilities:
        to_print += tem['Name']+"\n"
        to_return = main_1_single(model,tem['Description'],dataset_name,tem['Name'],DataSize,DemoNum,DiverNum,OptionNum)
        to_print+="\n######\n**{}**\n{}".format(tem['Name'],to_return)
        to_print += "\n\n"
    return to_print

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
    OptionNum = task['OptionNum']
    keys = list(task['abilities'].keys())
    keys = keys[len(keys)//2:]
    for sub_topic in keys:
        cur_des = task['abilities'][sub_topic]
        main_1_single(model,cur_des,dataset_name,sub_topic,DataSize,DemoNum,DiverNum,OptionNum)

if __name__ == "__main__":
    main()