# Steps for Generating Your Tailored Benchmark with BenchMaker

With this repository, you can achieve: input any demands for the capability you want to evaluate and receive a high-quality, customized benchmark.

For more details, see *LLM-Powered Benchmark Factory: Reliable, Generic, and Efficient*.

## Method 1: Run with **Gradio**
### Step-1:
Download all the required libraries and modify the `API_all.py` file as required to configure your API model.
### Step-2:
Run `gradio_demo.py` with the command `gradio gradio_demo.py` for an intuitive way to generate your customized benchmark.


## Method 2: Run with python file

### Step-1:
Download all the required libraries.

### Step-2:
Modify the `API_all.py` file as required to configure your API model.

### Step-3:
Define your assessment demands as in the JSON file of task_des.

### Step-4:
Modify the task_name in `final_generate_attribute_0.py` and run it.

### Step-5:
Modify the task_name in `final_LLMasBenchmarkGenerator_1.py` and run it.

### Step-6:
Modify the task_name in `final_decode_2.py` and run it.

### Step-7:
At this point, you can see the generated benchmark in `generated_benchmark`. If you want to further evaluate **faithfulness**, **alignment**, and **semantic diversity**, you can run `final_get_faithfulness_3_1.py`, `final_get_relevance_3_2.py`, and `final_get_embedding_3_0.py`, respectively.
You need to configure your embedding model in `final_get_embedding_3_0.py`.
