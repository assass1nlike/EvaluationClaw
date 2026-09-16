import gradio as gr
import pandas as pd
import tempfile
import os
import json
from final_generate_attribute_0 import main_0
from final_LLMasBenchmarkGenerator_1 import main_1
from final_decode_2 import main_2
from final_get_faithfulness_3_1 import main31
from final_get_embedding_3_0 import main30
from final_get_relevance_3_2 import main32

# Example apply function, you need to implement it according to actual requirements
def apply(benchmark_name, model_name, abilities_df, num_options, num_questions):
    # Convert DataFrame to a list of dictionaries
    abilities = abilities_df.to_dict(orient="records")

    # Filter out rows where name or description is empty
    abilities = [ability for ability in abilities if ability.get("Name") and ability.get("Description")]

    if not abilities:
        return "Error: At least one valid ability description is required."

    # Simply return the input content as an example
    abilities_str = "\n".join([f"Name: {ability['Name']}, Description: {ability['Description']}" for ability in abilities])
    return (f"Benchmark Name: {benchmark_name}\n"
            f"Abilities:\n{abilities_str}\n"
            f"Number of options per multiple-choice question: {int(num_options)}\n"
            f"Number of questions per ability: {int(num_questions)}")


# Function to delete a row
def delete_ability(abilities_df, delete_index):
    abilities = abilities_df.copy()
    num_rows = len(abilities)

    if delete_index < 0 or delete_index >= num_rows:
        return abilities, f"Error: Row number {delete_index} does not exist. Current total rows: {num_rows}."

    # Delete the specified row
    abilities = abilities.drop(index=delete_index).reset_index(drop=True)
    return abilities, f"Successfully deleted row number {delete_index}."


# Download function: directly returns a fixed file path
def download_data(benchmark_name, model_name, num_Demo):
    file_path = "generated_benchmark/API_Com_syn/{}/{}/attr_deep_diffusion_difattr_diflabel_v2-{}_harder/data.json".format(benchmark_name, model_name, num_Demo)
    if not os.path.exists(file_path):
        return None  # Or you can return a string containing an error message
    return file_path


# Function to display images
def show_figure(benchmark_name, model_name, num_Demo):
    # Try to display PDF; if not possible, display JPG
    jpg_path = "generated_benchmark/API_Com_syn/{}/{}/attr_deep_diffusion_difattr_diflabel_v2-8_harder/wordfig.jpg".format(
        benchmark_name, model_name, num_Demo)
    if os.path.exists(jpg_path):
        return jpg_path
    else:
        return None  # Or return an error message


# Default ability data, using a list of lists format
default_benchmark = "MATH"
default_abilities = [
    ["Algebra", "Assess the model's proficiency in algebraic operations using Chinese"],
    ["Number Theory", "Assess the model's proficiency in number theory using Chinese"]
]
# default_benchmark = "Logical Reasoning"
# default_abilities = [
#     ["Deductive Reasoning", "Assess the model's ability to derive necessary conclusions from general principles or known premises using Chinese"],
#     ["Analogical Reasoning", "Assess the model's ability to derive conclusions or solutions through comparing similarities between two or more different entities using Chinese"]
# ]


with gr.Blocks() as demo:
    gr.Markdown("## LLM as Benchmark Generator")

    # Benchmark Name input
    benchmark_name = gr.Textbox(label="Benchmark Name", value=default_benchmark)
    model_name = gr.Textbox(label="Generator Model Name", value="4omini")
    # Number of options per multiple-choice question
    num_options = gr.Number(label="Number of options per multiple-choice question", value=4, precision=0, interactive=True)
    judge_model_name = gr.Textbox(label="Model used to judge Faithfulness and Relevance", value="qwen_plus")
    # Number of questions per ability
    num_questions = gr.Number(label="Number of questions per ability", value=50, precision=0, interactive=True)
    num_Demo = gr.Number(label="Hyperparameter: Number of examples for comparison", value=8, precision=0, interactive=True)
    num_Diver = gr.Number(label="Hyperparameter: Number of candidates to increase diversity", value=5, precision=0, interactive=True)

    # Abilities input, using Dataframe
    abilities = gr.Dataframe(
        headers=["Name", "Description"],
        label="Abilities Description",
        value=default_abilities,
        row_count=(1, "dynamic"),  # Set initial row count to 1 and allow dynamic addition
        interactive=True
    )

    # Delete functionality
    with gr.Row():
        delete_index = gr.Number(label="Row number of ability to delete (starting from 0)", value=0, precision=0, interactive=True)
        delete_btn = gr.Button("Delete Ability")
    # Operation when delete button is clicked
    delete_output = gr.Textbox(label="Delete Result", lines=1)
    delete_btn.click(
        fn=delete_ability,
        inputs=[abilities, delete_index],
        outputs=[abilities, delete_output]
    )

    # Submit buttons and output
    submit_btn1 = gr.Button("Step 1. Preprocess")
    submit_btn2 = gr.Button("Step 2. Generate")
    submit_btn3 = gr.Button("Step 3. Decode")
    submit_btn4 = gr.Button("Step 4-1 (option). Get Embedding")
    submit_btn5 = gr.Button("Step 4-2 (option). Get Faithfulness")
    submit_btn6 = gr.Button("Step 4-3 (option). Get Relevance")
    submit_btn7 = gr.Button("Step 5. Analyze")
    output = gr.Textbox(label="Output Result", lines=10)

    # Operations when submit buttons are clicked
    submit_btn1.click(
        fn=main_0,
        inputs=[benchmark_name, model_name, abilities, num_options, num_questions],
        outputs=output
    )
    submit_btn2.click(
        fn=main_1,
        inputs=[model_name, abilities, benchmark_name, num_questions, num_Demo, num_Diver, num_options],
        outputs=output
    )
    submit_btn3.click(
        fn=main_2,
        inputs=[benchmark_name, model_name, num_Demo, num_Diver, num_questions],
        outputs=output
    )
    submit_btn4.click(
        fn=main30,
        inputs=[benchmark_name, model_name, num_Demo],
        outputs=output
    )
    submit_btn5.click(
        fn=main31,
        inputs=[benchmark_name, model_name, num_Demo, judge_model_name],
        outputs=output
    )
    submit_btn6.click(
        fn=main32,
        inputs=[benchmark_name, model_name, num_Demo, abilities, judge_model_name],
        outputs=output
    )
    submit_btn7.click(
        fn=main_2,
        inputs=[benchmark_name, model_name, num_Demo, num_Diver, num_questions],
        outputs=output
    )

    # Download functionality
    with gr.Row():
        fixed_download_btn = gr.Button("Download Benchmark")
        fixed_download_file = gr.File(label="Download Benchmark")

    fixed_download_btn.click(
        fn=download_data,
        inputs=[benchmark_name, model_name, num_Demo],
        outputs=fixed_download_file
    )

    # New: Button to display images and image component
    with gr.Row():
        show_figure_btn = gr.Button("Word Frequency Display")
        figure_output = gr.Image(label="Word Frequency Image Display")

    show_figure_btn.click(
        fn=show_figure,
        inputs=[benchmark_name, model_name, num_Demo],
        outputs=figure_output
    )

demo.launch(share=True)