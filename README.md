# Large Language Model Synthesized Access Control Policy Verification

## Overview

This repository contains the code and experimental artifacts for verifying LLM-synthesized access control policies. Our research explores techniques for generating, analyzing, and verifying access control policies using large language models, with a focus on AWS IAM policies, Azure role definitions, and GCP IAM bindings using formal verification methods.

## Research Approach

Our methodology combines:
- **Natural Language Processing**: Converting policy descriptions to formal specifications
- **Formal Verification**: Using SMT solvers and model counting for policy analysis
- **Quantitative Analysis**: Measuring policy permissiveness and semantic equivalence
- **Pattern Synthesis**: Generating regex patterns from example strings
- **Policy Summarization**: Producing human-readable summaries of complex AWS, Azure, and GCP policies via regex simplification and resource path verification

We evaluate state-of-the-art language models on their ability to:
1. Generate syntactically and semantically correct policies
2. Comprehend and explain existing policies
3. Synthesize patterns that capture policy resource constraints
4. Maintain semantic equivalence across transformations
5. Summarize complex policy behaviors into concise, verifiable descriptions

## Repository Structure

```
├── artifacts/              # Quacky tool + interactive web demo with Docker deployment
│   ├── Dockerfile         # Multi-stage Docker build (ABC solver + FastAPI app)
│   ├── deploy.sh          # Deployment helper script
│   ├── src/               # Quacky source code (with modifications)
│   ├── web/               # FastAPI web interface
│   │   └── app.py         # SSE-based policy analysis web app
│   ├── samples/           # Sample AWS IAM policies
│   ├── iam-dataset/       # IAM dataset for experiments
│   └── tutorial.md        # Step-by-step usage tutorial
│
├── policysummarizer/       # Policy Summarization Experiments (NEW)
│   ├── regex_summarizer.py # Core regex-based policy summarizer (AWS/Azure/GCP)
│   ├── mutation_comparator.py # Policy mutation comparison
│   ├── assignment_generator.py # GCP IAM assignment generation
│   ├── binding_generator.py    # GCP IAM binding generation
│   ├── flatten_role.py    # Azure role definition flattening
│   ├── assignments/       # Generated GCP IAM assignments
│   ├── bindings/          # Generated GCP IAM bindings
│   ├── results/           # Summarization results
│   └── results_report.ipynb # Analysis and figures
│
├── CPCA/                   # Core Policy Comprehension Assessment framework
│   └── cpca.py            # Main experiment runner
│
├── Exp-1/                  # Policy Generation and Comparison
│   └── Exp-1.py           # Dual policy analysis
│
├── Exp-2/                  # Resource Summarization
│   ├── Exp-2.py           # Regex synthesis from policies
│   └── tests/             # Test cases
│
├── Exp-3/                  # Factors Affecting Summarization
│   └── Exp-3.py           # Multi-string analysis
│
├── Exp-4-Zelkova/         # Zelkova-based Verification
│   ├── Exp-4-Zelkova.py   # Z3 model enumeration
│   └── z3_model_enum.py   # SMT solving utilities
│
├── Dataset/               # AWS IAM Policy Dataset
├── Fine-tuning/           # Model Fine-tuning Experiments
├── Simplification-Exp/    # Policy Simplification Studies
└── regex/                 # Regex Generation Results
```

## Quick Start with Docker (Recommended)

The `artifacts/` directory contains a fully dockerized deployment of the Quacky tool and web interface:

```bash
cd artifacts/
docker build -t quacky .
docker run -e ANTHROPIC_API_KEY=your_key -p 8000:8000 quacky
# Access at http://localhost:8000
```

The Docker image builds the ABC solver from source and bundles all dependencies. Build time is approximately 5–10 minutes on first run.

## Prerequisites for Local Setup

- Python 3.8+
- API keys for LLM services (at least one required)
- ABC (Automata-Based model Counter)
- Quacky (included in `artifacts/` with modifications)

## Installation

1. Clone this repository

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up API keys:
   Create `.env` file with your keys:
   ```
   ANTHROPIC_API_KEY=your_key
   OPENAI_API_KEY=your_key
   GOOGLE_API_KEY=your_key
   ```

4. Install ABC solver:
   ```bash
   git clone https://github.com/vlab-cs-ucsb/ABC.git
   cd ABC && mkdir build && cd build
   cmake .. && make && sudo make install
   ```

5. Quacky is included in the `artifacts/` directory with necessary modifications.

## Experiments

### Experiment 1: Policy Generation and Comparison
Evaluates LLM capabilities in generating and comparing access control policies.
```bash
cd Exp-1/
python Exp-1.py
```

### Experiment 2: Resource Summarization
Tests the ability to generate concise regex patterns that summarize policy resources.
```bash
cd Exp-2/
python Exp-2.py
```

### Experiment 3: Factors Affecting Summarization Accuracy
Investigates how various factors (string count, complexity) affect pattern synthesis accuracy.
```bash
cd Exp-3/
python Exp-3.py
```

### Experiment 4: Zelkova-based Verification
Uses Z3 theorem prover for formal policy verification and model enumeration.
```bash
cd Exp-4-Zelkova/
python Exp-4-Zelkova.py
```

### CPCA: Comprehensive Policy Analysis
Full experimental framework for policy comprehension assessment.
```bash
cd CPCA/
python cpca.py --models <model_name> --policy-dir <path> --output-dir results
```

### Policy Summarizer (New)
Regex-based policy summarization with LLM-aided simplification and resource path verification. Supports AWS IAM policies, Azure role definitions/assignments, and GCP IAM role bindings.
```bash
cd policysummarizer/
python regex_summarizer.py
```

## Key Features

- **Policy Generation**: Natural language to AWS IAM policy conversion
- **Quantitative Comparison**: SMT-based policy space analysis
- **Pattern Synthesis**: Regex generation from example strings
- **Formal Verification**: Using ABC and Z3 solvers
- **Policy Summarization**: Automated regex simplification and resource verification
- **Interactive Demo**: Web-based interface with streaming results
- **Multi-Cloud Support**: AWS IAM, Azure RBAC, and GCP IAM policy analysis

## Technical Components

- **Quacky**: Translates policies to SMT-LIB format for model counting
- **ABC Solver**: Performs efficient model counting for policy analysis
- **Z3 Theorem Prover**: Used for formal verification in Exp-4
- **FastAPI Interface**: Web-based demo with SSE streaming in `artifacts/web/`

## Data

The `Dataset/` folder contains AWS IAM policies used in experiments. The `policysummarizer/` directory contains GCP IAM assignments/bindings and supports Azure role definitions. To use your own:
1. Place policies in JSON format in the appropriate folder
2. Update experiment scripts to point to your data
3. Results will be saved in CSV format in respective experiment folders

## Replication Notes

Due to the non-deterministic nature of language models, exact result replication may vary. However, the techniques and trends should be consistent. The Quacky tool in `artifacts/` includes necessary modifications for our experiments.

## Citation

If you use this code or our findings in your research, please cite:
```
[Citation information will be added upon publication]
```

## License

MIT License

## Contact

For questions about the experiments or techniques, please open an issue on GitHub.
