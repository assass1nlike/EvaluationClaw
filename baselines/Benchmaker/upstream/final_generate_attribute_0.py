import glob
import json
import openai
import os
import time
from API_all import Get

import re

def extract_first_digit_in_range(s):
    match = re.search(r'\b(10|[1-9])\b', s)
    if match:
        return int(match.group(1))
    return None


def get_attr1(s):
    to_store = {}
    result = re.search(r'\*\*\*Task\*\*\*(.*?)\*\*\*End of Task\*\*\*', s,re.DOTALL)
    if result:
        extracted_text = result.group(1).strip()
        to_store['task'] = extracted_text
    else:
        return None
    result = re.search(r'\*\*\*Question Content\*\*\*(.*?)\*\*\*End of Question Content\*\*\*', s,re.DOTALL)
    if result:
        extracted_text = result.group(1).strip()
        to_store['query'] = extracted_text
    else:
        return None
    result = re.search(r'\*\*\*Answer Choices\*\*\*(.*?)\*\*\*End of Answer Choices\*\*\*', s,re.DOTALL)
    if result:
        extracted_text = result.group(1).strip()
        to_store['option'] = extracted_text
    else:
        return None
    return to_store

def get_attr2(s):
    to_store = []
    result = re.search(r'\*\*\*Attribute Analysis\*\*\*(.*?)\*\*\*End of Attribute Analysis\*\*\*', s, re.DOTALL)
    if result:
        extracted_text = result.group(1).strip()
    else:
        return None
    extracted_text = extracted_text.split("***")[1:]
    for tem in extracted_text:
        tem = tem.split(":")
        cur_store = {}
        cur_store['attribute'] = tem[0].strip()
        if "##" not in tem[1]:return None
        cur_store['values'] = tem[1].strip().split("##")
        to_store.append(cur_store)
    return to_store

def get_attr2_1(s):
    to_return = []
    try:
        s=s.split("The Final Attributes")[-1]
        s=s.split("End of Final Attributes")[0]
        s=s.split("\n")
        for tt in s:
            if len(tt)<10:continue
            tt=tt.split(":")
            attr=tt[0].strip("\n").strip(" ")
            if 'attribute' in attr.lower():return None
            values = [t.strip(" ") for t in tt[1].split("##")]
            to_return.append({"attribute":attr,"values":values})
        return to_return
    except:
        return None

def get_attr3(s):
    to_store = {}
    s = s.split("!!!")
    s= [t for t in s if len(t)>10]
    for t in s:
        t = t.split("###")
        t = [tt for tt in t if len(tt)>10]
        level = t[0].strip("\n").strip(" ")
        summary = t[2].split('thoughts:')[-1].strip("\n").strip("{{").strip("}}").strip(" ").strip("\n")
        to_store[level] = summary
    return to_store

def get_attr4(s):
    s=s.split("Step 3:")[-1]
    s = s.split("The Difficulty Attributes")[-1]
    s = s.split("End of Difficulty Attributes")[0]
    s=s.split("\n")
    attrs={}
    for tem in s:
        if len(tem)<10:continue
        tem = tem.split("####")
        attr_name = tem[0].strip()
        tem = tem[1].split("##")
        attr_values = []
        for t in tem:
            if len(t)<3:continue
            t=t.split(":")
            attr_values.append((t[0].strip(),extract_first_digit_in_range(t[1])))
        sorted_attr_values = sorted(attr_values, key=lambda x: x[1])
        attrs[attr_name] = sorted_attr_values
    return attrs


def main_0_single(model,task_description,benchmark_name,key):
    dir_name = "API_Com_syn/{}/{}/attr".format(benchmark_name,model)
    n=1
    temp=1
    os.makedirs(dir_name + "/raw_data", exist_ok=True)
    prompt1 = open('prompts/attr1.txt').read()
    prompt2 = open('prompts/attr2.txt').read()
    prompt2_1 = open('prompts/attr2_1.txt').read()
    prompt4 = open('prompts/attr4.txt').read()
    # prompt4_1 = open('prompts/attr4_1.txt').read()
    Mod = Get()
    cans = ["A","B","C","D","E","F","G","H"]
    to_return = {}
    if True:
                major_subject = benchmark_name
                subject = benchmark_name
                print("\n\n\n")
                c_dir = dir_name + "/raw_data/{}###{}###{}/attrs".format(major_subject, subject, key)
                os.makedirs(c_dir, exist_ok=True)
                if os.path.exists(dir_name + "/raw_data/{}###{}###{}/attrs/attr1.json".format(major_subject, subject, key)):
                    with open(dir_name + "/raw_data/{}###{}###{}/attrs/attr1.json".format(major_subject, subject, key),"r")as f:
                        to_store = json.load(f)
                        f.close()
                else:
                    cur_prompt1 = prompt1.replace("{{ability}}",task_description)
                    cnt_num=0
                    while True:
                        if cnt_num>5:break
                        try:
                            cnt_num+=1
                            response, cost = Mod.calc(cur_prompt1, n=n, temp=temp, model=model)
                            print(response[0])
                            to_store = get_attr1(response[0])
                            if to_store is None:continue
                            with open(dir_name + "/raw_data/{}###{}###{}/attrs/attr1.json".format(major_subject, subject, key), "w") as f:
                                raw_data = to_store
                                json.dump(raw_data, f)
                                f.close()
                            break
                        except Exception as e:
                            print(e)
                            print("Sleep 10s")
                            time.sleep(10)
                to_return["Detailed Ability Description"] = to_store['task']
                to_return["Query Description"] = to_store['query']
                to_return["Candidates Description"] = to_store['option']
                print('Step 1 OK!\n')

                if os.path.exists(dir_name + "/raw_data/{}###{}###{}/attrs/attr2.json".format(major_subject, subject, key)):
                    with open(dir_name + "/raw_data/{}###{}###{}/attrs/attr2.json".format(major_subject, subject, key),"r")as f:
                        to_store_ = json.load(f)
                        f.close()
                else:
                    if True:
                        for j in range(5):
                            if os.path.exists(dir_name + "/raw_data/{}###{}###{}/attrs/attr2_{}.json".format(major_subject, subject, key,j)):continue
                            cnt_num = 0
                            cur_prompt2 = prompt2.replace("{{ability}}",key).replace("{{task content}}",to_store['task']).replace("{{task content analysis}}",to_store['query']).replace("{{option analysis}}",to_store['option'])
                            while True:
                                if cnt_num>5:break
                                try:
                                    cnt_num+=1
                                    response, cost = Mod.calc(cur_prompt2, n=n, temp=temp, model=model)
                                    print(response[0])
                                    to_store_ = get_attr2(response[0])
                                    if to_store_ is None:continue
                                    with open(dir_name + "/raw_data/{}###{}###{}/attrs/attr2_{}.json".format(major_subject, subject, key,j), "w") as f:
                                        raw_data = to_store_
                                        json.dump(raw_data, f)
                                        f.close()
                                    break
                                except Exception as e:
                                    print(e)
                                    print("Sleep 10s")
                                    time.sleep(10)
                        cur_dirs = glob.glob(dir_name + "/raw_data/{}###{}###{}/attrs/attr2_*.json".format(major_subject, subject, key))
                        datas=[]
                        for cur_dir in cur_dirs:
                            with open(cur_dir,'r')as f:
                                data = json.load(f)
                                f.close()
                            datas.append(data)
                        cnt_num = 0
                        cur_prompt2_1 = prompt2_1.replace("{{ability}}", key).replace("{{task content}}", to_store['task']).replace(
                            "{{task content analysis}}", to_store['query']).replace("{{option analysis}}", to_store['option'])
                        the_attributes=""
                        for tem in datas:
                            for tt in tem:
                                the_attributes+="{}: ".format(tt['attribute'])+"##".join(tt['values'])+"\n"
                        cur_prompt2_1=cur_prompt2_1.replace('{{attributes}}',the_attributes)
                        while True:
                            if cnt_num > 10: break
                            try:
                                cnt_num += 1
                                response, cost = Mod.calc(cur_prompt2_1, n=n, temp=temp, model=model)
                                print(response[0])
                                to_store_ = get_attr2_1(response[0])
                                if to_store_ is None: continue
                                with open(dir_name + "/raw_data/{}###{}###{}/attrs/attr2.json".format(major_subject, subject,
                                                                                                         key), "w") as f:
                                    raw_data = to_store_
                                    json.dump(raw_data, f)
                                    f.close()
                                break
                            except Exception as e:
                                print(e)
                                print("Sleep 10s")
                                time.sleep(10)

                    print('Step 2 OK!')
                to_return["General Attributes"] = "\n".join(t["attribute"]+": "+", ".join(t['values']) for t in to_store_)


                if True:
                    if not os.path.exists(dir_name + "/raw_data/{}###{}###{}/attrs/attr3.json".format(major_subject, subject, key)):
                        cnt_num = 0
                        cur_prompt4 = prompt4.replace("{{ability}}", key).replace("{{task content}}",
                                                                                  to_store['task']).replace(
                            "{{task content analysis}}", to_store['query']).replace("{{option analysis}}",
                                                                                    to_store['option'])
                        while True:
                            if cnt_num>10:break
                            try:
                                cnt_num+=1
                                response, cost = Mod.calc(cur_prompt4, n=n, temp=temp, model=model)
                                print(response[0])
                                to_store_ = get_attr4(response[0])
                                if to_store_ is None:continue
                                with open(dir_name + "/raw_data/{}###{}###{}/attrs/attr3.json".format(major_subject, subject, key), "w") as f:
                                    raw_data = to_store_
                                    json.dump(raw_data, f)
                                    f.close()
                                break
                            except Exception as e:
                                print(e)
                                print("Sleep 10s")
                                time.sleep(10)

                    else:
                        with open(
                                dir_name + "/raw_data/{}###{}###{}/attrs/attr3.json".format(major_subject, subject, key,
                                                                                            ), "r") as f:
                            raw_data = json.load(f)
                            f.close()
                print('Step 3 OK!')
                to_return["Difficulty Attributes"] = "\n".join(key+": "+", ".join([t[0] for t in raw_data[key]]) for key in raw_data.keys())
    return to_return

def main_0(benchmark_name, model,abilities_df, num_options, num_questions):
    abilities = abilities_df.to_dict(orient="records")
    to_print = ""
    for tem in abilities:
        to_print += tem['Name']+"\n"
        to_return = main_0_single(model, tem['Description'], benchmark_name, tem['Name'])
        for key in to_return.keys():
            to_print+="\n######\n**{}**\n{}".format(key,to_return[key])
        to_print += "\n\n"
    return to_print



def main():
    task_name = 'MMLUPro_My_4o'
    with open("task_des/{}.json".format(task_name),'r')as f:
        task = json.load(f)
        f.close()
    model = task['model']
    benchmark_name = task['benchmark_name']
    for sub_topic in task['abilities'].keys():
        cur_des = task['abilities'][sub_topic]
        main_0_single(model,cur_des,benchmark_name,sub_topic)

if __name__ == "__main__":
    main()