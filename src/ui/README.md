# Interface gráfica local

O dashboard em `src/ui/app.py` organiza as capacidades do repositório em uma interface web local. Ele reutiliza os loaders, o gerador e o comparador existentes; não cria uma segunda implementação das regras de geração.

## Início rápido

Na raiz do repositório:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run src/ui/app.py --server.address localhost
```

O Streamlit mostrará uma URL local, normalmente `http://localhost:8501`. O arquivo `.streamlit/config.toml` também define `localhost` como endereço padrão. A interface não mostra o valor de nenhuma chave de API.

O menu lateral permanece visível e permite trocar diretamente entre todas as seções.

## Seções da interface

| Seção | O que apresenta ou executa |
|---|---|
| **Visão geral** | Os oito projetos, totais de classes/pacotes/entrypoints/dependências, provedores configurados e estado das execuções. |
| **Projetos e análise estática** | Requisitos, módulos, pacotes, dependências, entrypoints, classes, papéis inferidos, artefatos adicionais e a arquitetura de referência quando disponível. Também permite atualizar a análise dos oito projetos após confirmação. |
| **Prompts diretos** | Prévia fiel de `zero_shot` e `few_shot`: system prompt, user prompt, evidências e schema JSON. O few-shot mostra os três exemplos atuais. |
| **Fluxo do agente** | Etapas `domain_analyst`, `structural_analyst`, `architect`, `critic` e `refiner`, prompts iniciais e traces de execuções reais. |
| **Executar experimentos** | Monta e dispara, após confirmação, os mesmos comandos do CLI para `direct`, `agent` ou ambos. Também oferece modo seco. |
| **Resultados gerados** | CSV final, grafo de comunicações, métricas de arquitetura/processo, prompt salvo e trace JSONL por execução. |
| **Comparação** | Aciona `run_comparison()`, registra os filtros usados em `ui_last_comparison.json` e permite baixar/explorar todos os relatórios CSV de `comparison_outputs/`. |
| **Configuração e documentação** | Provedores/modelos sem segredos, limites de execução, comandos de referência e fórmulas das métricas. |

## Roteiro de uso

1. Abra **Projetos e análise estática** para consultar os requisitos e evidências de
   cada sistema. A aba **Referência** é apenas visual; ela não participa de métricas
   de precisão, recall ou F1.
2. Consulte **Prompts diretos** para revisar o prompt que será enviado em `direct`.
   O template `few_shot` contém três exemplos genéricos e não aplica a regra de que
   N módulos devem produzir N serviços.
3. Consulte **Fluxo do agente** para ver os prompts dos papéis. O ciclo é
   arquiteto → crítico → refinador → crítico: o refinador só executa quando o crítico
   retorna uma revisão necessária, e para quando o crítico aprova ou atinge o limite
   configurado.
4. Em **Executar experimentos**, execute primeiro em modo seco. Ele constrói prompts
   e registra metadata, mas não faz chamadas de API nem produz um CSV final.
5. Para uma execução real, desative o modo seco e confirme a ação. Em seguida, use
   **Resultados gerados** para abrir a arquitetura final, métricas, prompt salvo e
   trace; use **Comparação** para gerar relatórios de `direct` versus `agent`.

## Execução segura

- A interface aceita apenas projetos descobertos em `systems/`, provedores/modelos declarados em `config.yaml`, outputs dentro de `outputs/` e relatórios dentro de `comparison_outputs/`.
- A atualização de análise estática reprocessa todos os projetos com o runner existente e sobrescreve apenas `analysis-results/static-analysis/`; ela exige confirmação explícita e não usa LLM.
- Processos de geração são iniciados com uma lista de argumentos, sem `shell=True`.
- Uma chamada real só é habilitada após confirmação explícita e se a variável de ambiente configurada para o provedor estiver presente. Por exemplo, DeepSeek usa `DEEPSEEK_API_KEY`.
- O modo seco não chama API, mas segue o comportamento do CLI e registra a condição em `outputs/metadata.csv`.
- Reexecutar uma mesma combinação pode sobrescrever o CSV, trace e prompt daquele caminho. O `metadata.csv` mantém uma nova linha de histórico.
- A interface bloqueia uma comparação quando o `metadata.csv` apontar para CSVs ou traces fora do diretório de outputs selecionado. Ela também impede que duas ações de escrita da interface ocorram ao mesmo tempo.
- Prompts e respostas brutas do trace são potencialmente sensíveis. Eles ficam ocultos por padrão na visualização de resultados.
- A prévia e as métricas de trace exibidas pela interface são limitadas a 1.000 eventos ou 4 MB; downloads pela interface são limitados a 10 MB e exigem confirmação para prompts/traces brutos. O comparador de linha de comando analisa o trace completo.
- Processos iniciados pela interface têm limite de duas horas. Os logs mostrados nela são limitados a 1 MB por fluxo para evitar que uma saída anormalmente grande trave o navegador.
- O painel de comparação aplica filtros por projeto, provedor, modelo, template e
  execução. Seus relatórios são derivados dos artefatos existentes e nunca chamam
  um LLM.

## Exemplo com DeepSeek

Na página **Executar experimentos**, selecione:

- provedor: `deepseek`;
- modelo: `deepseek-chat`;
- abordagens: `direct` e `agent`;
- templates: `zero_shot` e/ou `few_shot`.

O equivalente para um projeto no terminal é:

```powershell
python -m src.main --project pet-clinic --provider deepseek --model deepseek-chat --approach direct --approach agent --prompt-template zero_shot --prompt-template few_shot --runs 1 --save-prompts
```

Depois, use **Comparação** ou rode:

```powershell
python -m src.comparison.evaluate --outputs-dir outputs --comparison-dir comparison_outputs
```

## Limites dos dados exibidos

A análise estática é baseada em código-fonte e imports, não em traces de runtime. Papéis de classes e entrypoints são inferidos heuristicamente. A arquitetura de referência em `ground true/` é somente uma consulta visual: o comparador não a usa para calcular precisão, recall ou F1 automaticamente.
