# Microservice Decomposition Pipeline

Este repositório agora contém um pipeline em Python para gerar propostas de decomposição de sistemas monolíticos em microsserviços usando LLMs via API.

O pipeline combina:

- requisitos funcionais em CSV localizados dentro de `systems/`
- resultados de análise estática localizados em `analysis-results/static-analysis/`

Para cada combinação de projeto, provedor/modelo e template de prompt, o pipeline solicita uma proposta de arquitetura e salva uma única saída final em CSV.

## Estrutura principal

```text
.
├── systems/
├── analysis-results/static-analysis/
├── outputs/
├── src/
│   ├── main.py
│   ├── config.py
│   ├── project_loader.py
│   ├── static_analysis_loader.py
│   ├── requirements_loader.py
│   ├── prompt_builder.py
│   ├── llm_clients/
│   │   ├── openai_client.py
│   │   ├── anthropic_client.py
│   │   └── deepseek_client.py
│   ├── response_parser.py
│   ├── csv_writer.py
│   └── metadata_writer.py
├── config.yaml
├── requirements.txt
└── .env.example
```

## Configuração

1. Crie e ative um ambiente virtual Python.
2. Instale as dependências:

```bash
pip install -r requirements.txt
```

3. Crie um arquivo `.env` a partir de `.env.example`:

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
DEEPSEEK_API_KEY=...
```

4. Ajuste os modelos em `config.yaml` se quiser trocar os defaults.

Os nomes de modelo, número de runs, tentativas máximas e templates ficam configuráveis em `config.yaml` e também podem ser filtrados pela CLI. O padrão atual é `1` execução por combinação.

Se algum modelo novo reclamar de parâmetros como `temperature`, você pode definir:

```yaml
temperature: null
```

O pipeline também tenta fazer retry automático sem `temperature` quando a API indicar que o parâmetro foi descontinuado para aquele modelo.
Para modelos `gpt-5*`, o client já evita enviar `temperature` por padrão.

## Como executar

Executar todos os experimentos:

```bash
python -m src.main --systems-dir systems --static-analysis-dir analysis-results/static-analysis --output-dir outputs
```

Executar para todos os provedores habilitados no `config.yaml` e salvar os prompts:

```bash
python -m src.main --output-dir outputs --save-prompts
```

Executar apenas um projeto:

```bash
python -m src.main --project 7ep
```

Executar apenas um provedor/modelo/template:

```bash
python -m src.main --project pet-clinic --provider openai --model gpt-5.5-2026-04-23 --prompt-template zero_shot
```

Validar descoberta e construção dos prompts sem chamar API:

```bash
python -m src.main --project 7ep --provider openai --prompt-template zero_shot --runs 1 --dry-run
```

Ver os prompts no terminal sem chamar API:

```bash
python -m src.main --project 7ep --dry-run --print-prompts
```

Salvar os prompts em arquivo:

```bash
python -m src.main --project 7ep --provider openai --save-prompts
```

## Templates de prompt

Atualmente o pipeline implementa:

- `zero_shot`
- `few_shot`

O template `few_shot` adiciona um exemplo genérico antes dos dados reais para orientar o modelo sem contaminar o domínio do sistema analisado.

## Estratégia de saída

Cada chamada ao modelo pede JSON estruturado neste formato:

```json
{
  "microservices": [
    {
      "microservice_name": "Order Service",
      "responsibility": "Manages order creation, order status, and order history.",
      "communicates_with": ["Customer Service", "Payment Service"]
    }
  ]
}
```

O pipeline:

1. valida o JSON com Pydantic
2. tenta reparar respostas quase válidas
3. repete a chamada até o limite configurado se necessário
4. converte a resposta validada para CSV

O CSV final sempre tem exatamente 3 colunas:

```csv
microservice_name,responsibility,communicates_with
Order Service,"Manages order creation, order status, and order history.","Customer Service;Payment Service"
```

## Onde os resultados ficam

Os arquivos de saída ficam organizados em:

```text
outputs/{project_name}/{provider}/{model_name}/{prompt_template}/run_{n}.csv
```

Se `--save-prompts` for usado, o pipeline também salva:

```text
outputs/{project_name}/{provider}/{model_name}/{prompt_template}/run_{n}.prompt.txt
```

Também é criado:

```text
outputs/metadata.csv
```

Esse arquivo registra:

- projeto
- provedor
- modelo
- template
- run
- caminho do arquivo
- timestamp
- status
- erro, se houver

## Observações

- As chaves de API não ficam hardcoded no código.
- O loader de requisitos é tolerante a nomes de colunas diferentes.
- O loader de análise estática aceita `.csv`, `.json`, `.txt` e `.md`.
- O pipeline usa por padrão a análise estática já gerada em `analysis-results/static-analysis/`.

## Avaliação das decomposições

O repositório também inclui um módulo de avaliação em `src/evaluation/`.

Executar a avaliação de todos os `run_*.csv` em `outputs/`:

```bash
python -m src.evaluation.evaluate_all --systems-dir systems --outputs-dir outputs --evaluation-dir evaluation_outputs
```

Filtros opcionais:

```bash
python -m src.evaluation.evaluate_all --project pet-clinic --provider anthropic --prompt-template zero_shot
```

Arquivos gerados:

```text
evaluation_outputs/
  metrics_by_run.csv
  metrics_by_service.csv
  metric_applicability_report.csv
  errors.csv
```

### Fórmulas implementadas primeiro

- `number_of_microservices`: número de linhas válidas no CSV.
- `number_of_communications`: número de arestas válidas no grafo declarado por `communicates_with`.
- `communication_density`: `edges / (n * (n - 1))` para grafo direcionado; se `n <= 1`, retorna `0`.
- `average_outgoing_communications`: `edges / n`.
- `isolated_services_count`: serviços com grau de entrada e saída iguais a `0`.
- `isolated_services_ratio`: `isolated_services_count / n`.
- `average_responsibility_length`: média do número de palavras das responsabilidades.
- `incoming_communications` e `outgoing_communications`: por microsserviço.
- `declared_inter_service_coupling`: mesma densidade declarada do grafo textual.

### Fórmulas estruturais implementadas

- `relational_cohesion_rc`: `internal_relations / possible_internal_relations`, com `possible_internal_relations = n * (n - 1) / 2`.
- `afferent_coupling_ac`: média de dependências externas que apontam para componentes internos de cada serviço.
- `efferent_coupling_ec`: média de dependências externas saindo dos componentes internos de cada serviço.
- `instability`: média de `EC / (EC + AC)` por serviço. Convenção adotada: se `EC + AC = 0`, então `instability = 0`.
- `inter_microservices_coupling`: média de `interactions_between_a_b / max(size_a, size_b)` para pares de serviços.
- `structural_modularity_quality_smq`: `SMQ = (average_cohesion - average_coupling) / (average_cohesion + average_coupling)`.
- `non_extreme_distribution_ned`: `services_with_acceptable_size / total_services`.

### Limitações importantes

- O avaliador não inventa métricas estruturais quando faltam dados como `component_to_service_mapping`.
- Quando uma métrica estrutural não pode ser calculada, ela é registrada como `missing_required_data`.
- Algumas métricas têm fallback explícito e separado, como:
  - `declared_inter_service_coupling`
  - `responsibility_domain_similarity`
  - `requirement_service_semantic_alignment`
- Esses fallbacks são textuais e não substituem métricas estruturais reais.

### Dependências da avaliação

- `pandas` para leitura e escrita dos CSVs.
- `networkx` para métricas baseadas em grafo quando disponível.

## Gráficos da avaliação

Também é possível gerar um dashboard HTML com gráficos SVG a partir dos arquivos em `evaluation_outputs/`.

Comando:

```bash
python -m src.evaluation.generate_charts --evaluation-dir evaluation_outputs --charts-dir evaluation_outputs/charts
```

Arquivos gerados:

```text
evaluation_outputs/charts/
  index.html
  run_metric_*.svg
  provider_summary_*.svg
  prompt_summary_*.svg
  applicability_by_metric.svg
  applicability_by_project.svg
  applicability_summary.html
```

O arquivo principal para navegação é:

```text
evaluation_outputs/charts/index.html
```

Filtros opcionais:

```bash
python -m src.evaluation.generate_charts --project pet-clinic
python -m src.evaluation.generate_charts --provider anthropic --prompt-template few_shot
```
