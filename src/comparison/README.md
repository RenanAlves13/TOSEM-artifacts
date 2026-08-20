# Comparação automática: `direct` versus `agent`

Este módulo calcula métricas descritivas das propostas de microsserviços geradas pelas duas estratégias do repositório:

- `direct`: uma chamada principal ao modelo com requisitos e evidências estáticas;
- `agent`: análise de domínio, análise estrutural, síntese arquitetural, crítica e possível refinamento.

Ele usa somente os artefatos produzidos pelo próprio pipeline: CSV final, `metadata.csv` e trace JSONL. Não chama LLMs e não modifica as propostas originais.

## Execução

Após executar as duas estratégias com condições equivalentes, rode:

```powershell
python -m src.comparison.evaluate --outputs-dir outputs --comparison-dir comparison_outputs
```

Exemplo de geração pareada:

```powershell
python -m src.main --project pet-clinic --provider openai --prompt-template few_shot --approach direct --approach agent --runs 5 --save-prompts
python -m src.comparison.evaluate --project pet-clinic --comparison-dir comparison_outputs
```

Filtros disponíveis:

```powershell
python -m src.comparison.evaluate --project pet-clinic --provider openai --model gpt-5.5-2026-04-23 --prompt-template few_shot --run-id run_1
```

Uma responsabilidade é considerada curta quando contém menos de cinco palavras por padrão. O limite pode ser alterado:

```powershell
python -m src.comparison.evaluate --min-responsibility-words 8
```

O diretório padrão `comparison_outputs/` contém dados derivados e é ignorado pelo Git.

## Uso pela interface gráfica

A página **Comparação** da interface Streamlit executa o mesmo `run_comparison()` do
CLI. Ela permite selecionar diretórios de origem e relatórios, filtrar por projeto,
provedor, modelo, template e `run`, e baixar cada CSV produzido. A ação não chama um
LLM nem altera CSVs de arquitetura ou traces; ela somente atualiza os dados derivados
em `comparison_outputs/` e registra os filtros usados em `ui_last_comparison.json`.

Antes de calcular, a interface valida que os artefatos indicados no `metadata.csv`
estão dentro do diretório de outputs selecionado. Ela bloqueia a operação se encontrar
um caminho externo ou inseguro.

## Entradas aceitas

### Layout atual

```text
outputs/
  metadata.csv
  <project>/<approach>/<provider>/<model>/<prompt-template>/run_<n>.csv
  <project>/<approach>/<provider>/<model>/<prompt-template>/run_<n>.trace.jsonl
```

`<approach>` deve ser `direct` ou `agent`. O CSV precisa ter as colunas:

```text
microservice_name,responsibility,communicates_with
```

O campo `communicates_with` usa `;` como separador de destinos.

### Layout legado

Também é aceito o formato sem a pasta de abordagem:

```text
outputs/<project>/<provider>/<model>/<prompt-template>/run_<n>.csv
```

Ele é classificado como `direct`.

### `metadata.csv`

Quando existe, `metadata.csv` é usado para obter status, timestamp e os caminhos canônicos de CSV/trace. Esses caminhos precisam permanecer dentro do diretório informado em `--outputs-dir`; uma linha que aponte para fora é rejeitada e registrada em `comparison_issues.csv`. O comparador aceita metadados antigos sem `approach` e os trata como `direct`.

Se houver múltiplas linhas de metadados para a mesma execução, o último registro bem-sucedido é usado e o caso fica registrado como aviso. Isso é importante porque o gerador pode sobrescrever `run_<n>.csv` em uma reexecução.

Arquivos encontrados sem metadados ainda são calculados, mas aparecem com `metadata_status=inferred` e aviso no relatório de pareamento.
Nesses casos, o nome do modelo vem da pasta sanitizada do caminho. Nomes que diferem apenas por `/`, `\` ou `:` não podem ser distinguidos sem `metadata.csv`; o relatório registra esse risco como aviso.

## Pareamento entre estratégias

Uma comparação válida exige uma execução de cada abordagem com a mesma chave:

```text
(project_name, provider, model_name, prompt_template, run_id)
```

Por exemplo, `run_2` de `direct/openai/gpt-5.5/few_shot` é comparado com `run_2` de `agent/openai/gpt-5.5/few_shot` do mesmo projeto.

`pairing_report.csv` classifica cada chave como:

| Status | Significado |
|---|---|
| `paired` | CSVs válidos nas duas estratégias; pode entrar em deltas e similaridade. |
| `missing_direct` / `missing_agent` | Uma das abordagens não foi encontrada. |
| `invalid_direct_output` / `invalid_agent_output` | O CSV existe, mas não pôde ser calculado. |
| `duplicate_direct` / `duplicate_agent` | Mais de um resultado foi associado à mesma chave. |
| `ambiguous_model_identity` | Os dois `metadata.csv` informam nomes de modelo diferentes que geram a mesma pasta sanitizada. |

Resultados `duplicate_*` e `ambiguous_model_identity` permanecem nos relatórios por execução para auditoria (`architecture_metrics_by_run.csv`, `process_metrics_by_run.csv` e `run_metrics_long.csv`), mas são excluídos de `approach_metric_summary.csv` e `stability_by_approach.csv`. Assim, não contaminam os agregados de uma abordagem mesmo quando não existe um par válido.

O pareamento é descritivo. Sem um `experiment_id` ou hash de configuração, execuções históricas com a mesma chave podem pertencer a lotes diferentes; esse risco deve ser registrado ao interpretar os resultados.

Internamente, a pasta do modelo é comparada pela forma sanitizada usada pelo gerador. Quando os dois lados possuem metadados, os nomes brutos do modelo também precisam ser iguais; caso contrário, o par é rejeitado como ambíguo. Se um dos lados não possuir metadados, a correspondência pela pasta é aceita com aviso, pois não há informação suficiente para desambiguar nomes como `foo/bar` e `foo_bar`.

## Arquivos gerados

| Arquivo | Conteúdo |
|---|---|
| `architecture_metrics_by_run.csv` | Uma linha por execução descoberta; métricas de estrutura e texto são preenchidas somente para CSVs válidos, com `architecture_status` para os demais casos. |
| `process_metrics_by_run.csv` | Métricas extraídas de cada trace; valores indisponíveis ficam vazios, não zero. |
| `run_metrics_long.csv` | Versão longa, uma métrica numérica por linha; adequada para análise posterior. |
| `approach_metric_summary.csv` | Média, mediana, desvio-padrão populacional, mínimo e máximo por abordagem, excluindo execuções com identidade ambígua ou resultado duplicado. |
| `pairing_report.csv` | Diagnóstico de quais `direct × agent` puderam ser pareados. |
| `paired_architecture_similarity.csv` | Similaridade entre conjuntos normalizados de serviços e comunicações de cada par. |
| `paired_metric_deltas.csv` | Para cada métrica pareada, valores direto/agente e `agente - direto`. |
| `paired_metric_summary.csv` | Resumo dos deltas por projeto, modelo, prompt e métrica. |
| `stability_by_approach.csv` | Variação e similaridade entre repetições da mesma abordagem, excluindo execuções com identidade ambígua ou resultado duplicado. |
| `comparison_issues.csv` | CSVs ausentes/malformados, traces parciais e avisos de descoberta. |

## Notação

Para uma execução:

- `N`: número de linhas válidas de microsserviço no CSV;
- `U`: número de nomes de serviço únicos após remover diferença de maiúsculas/minúsculas e espaços repetidos;
- `E`: conjunto de comunicações direcionadas válidas entre serviços declarados;
- `|E|`: quantidade de arestas válidas;
- `d_out(s)` e `d_in(s)`: graus de saída e entrada do serviço `s`;
- `w_i`: número de palavras da responsabilidade do serviço `i`;
- `T_i`: conjunto de tokens da responsabilidade do serviço `i`.

Uma comunicação é válida somente se o destino também for um serviço declarado e for diferente da origem. Isso evita que um nome digitado incorretamente aumente artificialmente as métricas do grafo.

## Métricas de arquitetura

### Integridade do CSV e do grafo

| Métrica | Cálculo | Interpretação |
|---|---|---|
| `service_count` | `N` | Número de serviços com nome e responsabilidade não vazios. |
| `unique_service_count` | `U` | Serviços distintos após normalização de caixa e espaços. |
| `duplicate_service_name_count` | `N - U` | Nomes repetidos; idealmente zero. |
| `malformed_service_row_count` | Linhas sem nome ou responsabilidade | Essas linhas são ignoradas no cálculo estrutural. |
| `raw_declared_communication_count` | Total de destinos não vazios antes de deduplicar | Mostra todas as declarações recebidas. |
| `declared_communication_count` | Número de pares direcionados únicos declarados | Inclui autorreferências e destinos inválidos. |
| `duplicate_communication_count` | `raw_declared_communication_count - declared_communication_count` | Declarações repetidas da mesma aresta. |
| `valid_communication_count` | `|E|` | Arestas entre dois serviços distintos realmente declarados. |
| `invalid_communication_target_count` | Arestas únicas cujo destino não pertence a `U` | Indica referências inválidas ou inconsistentes. |
| `self_communication_count` | Arestas `s → s` | Autorreferências; não entram no grafo interserviços. |

### Estrutura de comunicação

| Métrica | Fórmula | Convenção |
|---|---|---|
| `communication_density` | `|E| / (U × (U - 1))` | Grafo dirigido sem loops. Se `U < 2`, vale `0`. |
| `average_outgoing_communications` | `Σ d_out(s) / U` | Fica vazia quando não há serviços. |
| `max_outgoing_communications` | `max d_out(s)` | Maior número de dependências declaradas por um serviço. |
| `average_incoming_communications` | `Σ d_in(s) / U` | Fica vazia quando não há serviços. |
| `max_incoming_communications` | `max d_in(s)` | Ajuda a identificar um possível hub. |
| `isolated_services_count` | `#{s : d_in(s)=0 ∧ d_out(s)=0}` | Serviços sem comunicação declarada. |
| `isolated_services_ratio` | `isolated_services_count / U` | Fica vazia quando `U=0`. |
| `reciprocal_communication_pair_count` | `#{ {a,b} : a→b ∈ E ∧ b→a ∈ E }` | Cada par bidirecional é contado uma vez. |
| `reciprocity_ratio` | `(2 × reciprocal_communication_pair_count) / |E|` | Proporção de arestas que pertencem a um par recíproco; vale `0` quando `|E|=0`. |

Essas métricas descrevem o grafo declarado pelo modelo. Densidade ou reciprocidade baixa não é automaticamente melhor: a interpretação depende do domínio e das necessidades de integração.

### Texto das responsabilidades

| Métrica | Cálculo | Interpretação |
|---|---|---|
| `total_responsibility_word_count` | `Σ w_i` | Volume total de descrição. |
| `average_responsibility_word_count` | `(Σ w_i) / N` | Tamanho médio das responsabilidades. |
| `responsibility_word_count_stddev` | `sqrt((Σ(w_i - média)^2) / N)` | Desvio-padrão populacional; `0` para uma única responsabilidade. |
| `min_responsibility_word_count` / `max_responsibility_word_count` | `min(w_i)` / `max(w_i)` | Extremos de detalhamento. |
| `short_responsibility_count` | `#{i : w_i < k}` | `k` é `--min-responsibility-words`, padrão `5`. |
| `short_responsibility_ratio` | `short_responsibility_count / N` | Fica vazia quando `N=0`. |
| `average_responsibility_token_jaccard` | média de `J(T_i,T_j)` para todos os pares `i < j` | Indício lexical de sobreposição entre responsabilidades. |

Para `J(T_i,T_j)`, o comparador usa Jaccard:

```text
J(A, B) = |A ∩ B| / |A ∪ B|
```

Os tokens são sequências alfanuméricas/apóstrofo/hífen, normalizadas para minúsculas; tokens com até dois caracteres são descartados. Não há remoção de stop words nem análise semântica. Por isso, a métrica é um indício lexical, e não uma medida definitiva de coesão ou sobreposição de domínio.
Quando os dois conjuntos de tokens de um par estão vazios, o comparador usa `J=1` (dois conjuntos vazios são tratados como idênticos).

## Métricas entre repetições: estabilidade

`stability_by_approach.csv` agrupa execuções com mesmo projeto, abordagem, provedor, modelo e template de prompt.

Para cada par de repetições `r` e `s`, calcula:

```text
service_set_jaccard(r, s) = |S_r ∩ S_s| / |S_r ∪ S_s|
communication_set_jaccard(r, s) = |E_r ∩ E_s| / |E_r ∪ E_s|
```

O relatório apresenta a média de todos os pares possíveis. Também informa média e desvio-padrão populacional de `service_count` e `valid_communication_count`.

Com menos de duas repetições, `run_pair_count=0` e as duas médias de Jaccard ficam vazias. Para qualquer Jaccard deste módulo, dois conjuntos vazios recebem `1` e um conjunto vazio comparado a um não vazio recebe `0`.

Nomes de serviços são comparados por igualdade após normalização de caixa/espaços. `Order Service` e `Ordering Service`, por exemplo, contam como diferentes. Use essa métrica como estabilidade de nomenclatura e estrutura explícita, não como equivalência semântica.

## Comparação pareada `agent - direct`

Para cada par válido, `paired_metric_deltas.csv` calcula:

```text
delta = valor_agent - valor_direct
relative_change_from_direct = delta / |valor_direct|
```

Quando o valor direto é zero, a mudança relativa fica vazia para evitar divisão por zero. `paired_metric_summary.csv` resume os deltas com média, mediana, desvio-padrão populacional e quantidades em que o agente ficou acima, igual ou abaixo.

Os termos `agent_higher_count` e `agent_lower_count` são deliberadamente descritivos: não assumem que maior ou menor seja melhor. Por exemplo, mais chamadas ao LLM normalmente representam mais custo; já mais cobertura de interações pode ou não ser desejável conforme o caso.

`paired_architecture_similarity.csv` calcula Jaccard entre nomes de serviços normalizados (caixa e espaços) e dois conjuntos de arestas: `declared_communication_set_jaccard` inclui todas as comunicações declaradas, enquanto `communication_set_jaccard` usa somente arestas válidas entre serviços declarados. Similaridade alta mede concordância entre as estratégias, não correção. A segunda métrica pode ignorar erros de destino; por isso as duas colunas devem ser lidas junto com `invalid_communication_target_count`.

## Métricas de processo pelos traces

Os dois fluxos escrevem traces JSONL. No fluxo direto, há chamadas com o papel `direct_generator`. No fluxo agente, os papéis podem incluir `domain_analyst`, `structural_analyst`, `architect`, `critic` e `refiner`.

| Métrica | Cálculo |
|---|---|
| `trace_available` | `1` se o trace existe; `0` se não existe. Os demais valores ficam vazios quando o trace está ausente. |
| `trace_event_count` | Número de eventos JSON válidos. |
| `trace_invalid_json_line_count` | Linhas JSONL ilegíveis ou que não representam um objeto de evento; eventos válidos ainda são aproveitados. |
| `llm_call_count` | Eventos `agent_call`, incluindo tentativas com erro. |
| `successful_llm_call_count` | Eventos `agent_call` com `status=success`. |
| `failed_llm_call_count` / `failed_llm_call_ratio` | `api_error_count + parse_error_count` e esse total dividido por `llm_call_count`. |
| `api_error_count` / `parse_error_count` | Chamadas com esses respectivos status. |
| `retry_call_count` | Chamadas cujo campo `attempt > 1`. |
| `retry_call_ratio` | `retry_call_count / llm_call_count`. |
| `total_call_duration_ms` | Soma de `duration_ms` de todas as chamadas. |
| `average_call_duration_ms` / `max_call_duration_ms` | Média e máximo de `duration_ms` das chamadas. |
| `trace_elapsed_ms` | Diferença entre o primeiro e o último timestamp válido do trace. |
| `total_system_prompt_char_count` | Soma dos caracteres de todos os system prompts enviados. |
| `total_user_prompt_char_count` | Soma dos caracteres dos user prompts enviados. |
| `total_response_char_count` | Soma dos caracteres das respostas brutas disponíveis. |
| `distinct_role_count` | Número de papéis distintos que fizeram chamadas. |
| `critic_round_count` | Eventos `critique_decision`. |
| `revision_request_count` | Decisões do crítico com `requires_revision=true`. |
| `critic_issue_count` | Soma do campo `issue_count` das decisões do crítico. |
| `refinement_round_count` | Snapshots com `phase=refined`. |
| `workflow_converged` | `1` quando há evento `workflow_converged`; caso contrário `0`. |
| `stopped_by_iteration_limit` | `1` quando há evento `workflow_stopped`; caso contrário `0`. |
| `services_added_during_refinement_count` / `services_removed_during_refinement_count` | Soma, respectivamente, das listas `services_added` e `services_removed` registradas nos snapshots com `phase=refined`. |
| `interactions_added_during_refinement_count` / `interactions_removed_during_refinement_count` | Soma equivalente das listas `interactions_added` e `interactions_removed` dos snapshots refinados. |
| `final_snapshot_service_count` / `final_snapshot_communication_count` | Tamanho do último snapshot do trace; diagnóstico, pois o CSV é a fonte canônica da arquitetura final. |

Os contadores de caracteres são proxies de volume de contexto, não contagem de tokens. O pipeline atual não registra tokens cobrados nem custo monetário por chamada; portanto, custo real não é calculado automaticamente.

No dashboard, os termos “caracteres” em prompts, evidências e traces têm esse sentido:
cada letra, número, espaço ou sinal de pontuação conta como um caractere. Eles ajudam a
comparar o volume textual enviado, mas não substituem a contagem de tokens ou a fatura
do provedor.

Quando um trace disponível não tem chamadas, seus contadores e somas de chamadas ficam em `0`, enquanto razões, média e máximo de duração ficam vazios. Com menos de dois timestamps válidos, `trace_elapsed_ms` vale `0`. Uma duração não finita é substituída por `0` e torna o trace `partial`.

## Status e limitações

- O comparador mede forma, consistência textual, estabilidade e processo. Ele não prova que uma arquitetura é correta.
- Precisão, recall e F1 exigem um gold standard independente de serviços e interações.
- Coesão/acoplamento estrutural por microsserviço exigem um mapeamento confiável de classes/pacotes para os serviços propostos; esse mapeamento não existe no CSV final.
- Cobertura funcional exige uma relação requisito → serviço, que também não é emitida automaticamente.
- Métricas de runtime exigem traces de execução e medições de rede/payload.
- Um trace `partial` possui linhas inválidas, valores de duração não finitos ou não contém o evento terminal `run_finished`; as métricas disponíveis usam os eventos válidos restantes.
- Traces contêm prompts e respostas brutas. Trate os arquivos como artefatos potencialmente sensíveis antes de compartilhá-los.

Para uma comparação justa, mantenha projeto, provedor, versão do modelo, template, configuração e número de repetições iguais nas duas estratégias.
