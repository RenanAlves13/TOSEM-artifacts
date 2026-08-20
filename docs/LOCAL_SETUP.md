# Instalação e execução local

Este guia prepara uma cópia do repositório para executar a análise estática, gerar
propostas com LLM e abrir a interface gráfica local.

## Pré-requisitos

- Git;
- Python 3.10 ou superior;
- uma chave de API de pelo menos um provedor configurado, apenas para execuções reais.

Java e Maven não são necessários para o fluxo padrão: a análise estática lê o código
fonte, os arquivos de build e as declarações `import`. Eles só são necessários se você
pretender executar os sistemas Java incluídos em `systems/`.

## 1. Obter o código e criar o ambiente virtual

```powershell
git clone https://github.com/RenanAlves13/TOSEM-artifacts.git
cd TOSEM-artifacts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

No macOS ou Linux, ative o ambiente com:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Configurar uma chave de API

Crie o arquivo local `.env` a partir do exemplo. Ele é ignorado pelo Git.

```powershell
Copy-Item .env.example .env
```

Para usar DeepSeek, preencha somente a variável abaixo no `.env`:

```env
DEEPSEEK_API_KEY=sua_chave_aqui
```

Os provedores e modelos habilitados ficam em `config.yaml`. Caso não possua chaves para
OpenAI ou Anthropic, selecione explicitamente `deepseek` na interface ou passe
`--provider deepseek` na linha de comando. Nunca publique o `.env` nem traces que
contenham prompts/respostas sensíveis.

## 3. Atualizar a análise estática

Os artefatos de análise estática versionados já permitem explorar o projeto. Para
recriá-los a partir dos sistemas atuais, execute:

```powershell
python "static analysis\analyze_systems.py"
```

Isso reescreve `analysis-results/static-analysis/`. Consulte
[`static analysis/README.md`](../static%20analysis/README.md) para o significado dos
arquivos gerados.

## 4. Validar sem custo de API

O modo seco descobre o projeto, carrega evidências e constrói os prompts, mas não envia
nenhuma chamada ao provedor nem produz um CSV final.

```powershell
python -m src.main --project 7ep --provider deepseek --model deepseek-chat --approach direct --approach agent --prompt-template zero_shot --runs 1 --dry-run --save-prompts
```

O metadata e as prévias de prompt ficam em `outputs/`, diretório ignorado pelo Git.

## 5. Executar as duas estratégias

Depois de validar o modo seco, remova `--dry-run`:

```powershell
python -m src.main --project 7ep --provider deepseek --model deepseek-chat --approach direct --approach agent --prompt-template zero_shot --prompt-template few_shot --runs 1 --save-prompts
```

`direct` faz uma geração principal. `agent` executa analista de domínio, analista
estrutural e arquiteto; depois o crítico aprova a proposta ou pede revisão ao refinador.
O número máximo de rodadas de revisão está em
`experiment.agent.max_refinement_rounds` no `config.yaml`.

## 6. Comparar os resultados

Quando houver uma execução `direct` e uma `agent` com o mesmo projeto, provedor, modelo,
template e `run`, calcule as métricas derivadas:

```powershell
python -m src.comparison.evaluate --outputs-dir outputs --comparison-dir comparison_outputs
```

Os CSVs da comparação são gravados em `comparison_outputs/` e também são ignorados pelo
Git. As fórmulas e limitações estão em
[`src/comparison/README.md`](../src/comparison/README.md).

## 7. Usar a interface gráfica

```powershell
python -m streamlit run src/ui/app.py --server.address localhost
```

Abra a URL mostrada pelo Streamlit (normalmente `http://localhost:8501`). A interface
permite consultar os projetos, revisar prompts, disparar modo seco ou execução real,
visualizar resultados e calcular a comparação. Veja
[`src/ui/README.md`](../src/ui/README.md) para o roteiro da interface e seus limites.

## Verificação automatizada

Execute os testes sem chamar LLMs:

```powershell
python -m unittest discover -s tests -v
```

## Problemas comuns

| Sintoma | Verificação |
|---|---|
| `ModuleNotFoundError` | Ative `.venv` e rode `python -m pip install -r requirements.txt`. |
| Falha de autenticação | Confirme a variável correspondente no `.env`, o nome do provedor e o modelo em `config.yaml`. |
| Não há projeto ou análise estática | Rode o script de análise estática e confirme que `systems/` e `analysis-results/static-analysis/` existem. |
| Não há pares na comparação | Execute `direct` e `agent` com a mesma combinação de projeto, provedor, modelo, template e `run`. |
| Porta 8501 ocupada | Acrescente `--server.port 8502` ao comando do Streamlit. |
