import glob
import random
import requests
import os
import json

# def get_embedding(data):
#     '''
#         Please implement this function to call your embedding model.
#
#         **Input:**
#         - `data`: string
#
#         **Output:**
#         - `embedding`: list
#     '''




def main30(dataset_name,generate_model,DemoNum):
    sub_names = ['attr_deep_diffusion_difattr_diflabel_v2-{}_harder'.format(DemoNum)]
    random.shuffle(sub_names)
    method = 'syn'
    sub_name = 'attr_deep_diffusion_difattr_diflabel_v2-{}_harder'.format(DemoNum)
    dir_name = "generated_benchmark/API_Com_{}/{}/{}/{}".format(method, dataset_name, generate_model, sub_name)
    if os.path.exists(dir_name+"/data.json"):
        with open(dir_name+"/data.json", 'r') as f:
                            datas = json.load(f)
                            f.close()
        os.makedirs(dir_name+"/Embed",exist_ok=True)
        if not os.path.exists(dir_name+"/embedding.json"):
                        random.shuffle(datas)
                        for tem in datas:
                            has_generated = [int(t.split('/')[-1].split('.')[0]) for t in glob.glob(dir_name+"/Embed/*")]
                            if tem['idx'] in has_generated:continue
                            print(len(has_generated))
                            to_test = tem['question']+' '+tem['candiates']
                            to_test=to_test.replace("\n",' ')
                            embed = get_embedding(to_test)
                            to_store = {
                                'raw':tem,
                                'embedding':embed
                            }
                            with open(dir_name+"/Embed/{}.json".format(tem['idx']),'w')as f:
                                json.dump(to_store,f)
                                f.close()
                        dirs = glob.glob(dir_name+"/Embed/*")
                        all_embeddings = []
                        for dir in dirs:
                            with open(dir,'r')as f:
                                cur_data = json.load(f)
                                f.close()
                            all_embeddings.append(cur_data)
                        with open(dir_name+"/embedding.json",'w')as f:
                            json.dump(all_embeddings,f)
                            f.close()
    return "Get All Embedding!"

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
    main30(dataset_name,model,DemoNum)



if __name__ == "__main__":
    main()