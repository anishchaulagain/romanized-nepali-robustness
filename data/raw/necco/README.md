# Nepali Cultural Commonsense Benchmark (NCCB)

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The **Nepali Cultural Commonsense Benchmark (NCCB)** is a research framework designed to evaluate and compare the performance of Large Language Models (LLMs) on Nepali cultural knowledge, etiquette, agriculture, and linguistics. It focuses on how well models understand traditional Nepali contexts across different language representations: **Pure Nepali (Devanagari)**, **Romanized Nepali**, and **English Translations**.

## 🌟 Key Features

*   **Multi-Domain Evaluation**: Benchmarks models across critical cultural categories: Cultural Etiquette, Agriculture, Festivals, Geography, Kinship, and Nepali Proverbs (Ukhan/Tukka).
*   **Cross-Linguistic Analysis**: Compares model performance across English, Nepali (Devanagari), and Romanized Nepali.
*   **Automated Visualization**: Generates high-quality heatmaps, comparative bar charts, and leaderboards.
*   **Scalable Automation**: Easily test multiple models via OpenRouter integration.

---

## 🚀 Workflow & Usage

To ensure proper logging and visualization, follow this specific workflow:

### 1. Run Model Evaluation
The evaluation scripts are located in the `automation/` folder.
1.  Navigate to the project root.
2.  Update `automation/model.txt` with the OpenRouter model IDs you wish to test.
3.  Run the evaluation:
    ```bash
    python automation/auto_evaluate.py
    ```
    *This will generate a `Result/` folder inside the `automation/` directory containing raw CSV outputs.*

### 2. Prepare for Visualization (Crucial Step)
Once the evaluation is complete, you must move the results to the root directory for the visualization suite to work:
1.  Locate the folder: `automation/Result/`.
2.  **Drag/Move** the `Result` folder from inside `automation/` to the **root** of the project.
3.  The root structure should now have a `Result/` directory containing folders for each model.

### 3. Generate Visualizations
Once the `Result/` folder is in the root, run the following scripts to generate insights:

*   **Model Benchmarking**: Compares all models in the `Result/` folder.
    ```bash
    python benchmark_models.py
    ```
*   **Linguistic Comparison**: Analyzes performance across different languages.
    ```bash
    python compare_languages.py
    ```
*   **Detailed Model Analysis**: Generates per-model metrics, confusion matrices, and category breakdowns.
    ```bash
    python visualize.py
    ```

---

## 📊 Analytics Provided

| Script | Outputs |
| :--- | :--- |
| `benchmark_models.py` | Global Heatmap, Cross-Model Bar charts, Overall Leaderboard |
| `compare_languages.py` | Linguistic Comparison (Devanagari vs Romanized vs English) |
| `visualize.py` | Confusion Matrices, Category Accuracy %, Precision/Recall/F1 Scores |

---

## 🛠️ Setup & Installation

### Prerequisites
*   Python 3.8+
*   OpenRouter API Key

### Installation
1.  **Clone the repository**:
    ```bash
    git clone git@github.com:Mezamenta-Nakama09/NeCCo.git
    cd NeCCo
    ```
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Setup Environment**:
    Create a `.env` file in the root directory:
    ```env
    OPENROUTER_API_KEY=your_api_key_here
    ```

## 📁 Project Structure

*   **/automation**: Contains `auto_evaluate.py` and the source `Data/` for evaluation.
*   **/Result**: (After moving) Contains model-specific CSVs and generated visualizations.
*   `benchmark_models.py`: Compiles global results from all model folders.
*   `compare_languages.py`: Performs cross-linguistic analysis.
*   `visualize.py`: Generates deep-dive metrics for each individual model.

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.
