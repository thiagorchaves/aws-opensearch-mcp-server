# AWS OpenSearch MCP, read-only

MCP em Python para investigar domínios do **Amazon OpenSearch Service** usando profiles AWS locais, incluindo SSO. O servidor foi desenhado para operação segura em CI, QA, produção e telemetry, sem ferramentas de escrita.

## O que ele entrega

- Profiles permitidos: `ci`, `qa`, `prod` e `telemetry`.
- Regiões permitidas por configuração.
- Descoberta de domínios com `boto3`.
- Acesso ao data plane com AWS Signature Version 4.
- Consultas limitadas por tamanho, timeout e quantidade de documentos.
- Redação de campos com aparência de segredo ou credencial.
- Diagnósticos específicos para shards, flood stage, mappings e timestamps antigos.
- Nenhum endpoint genérico de request e nenhuma ferramenta de escrita.

## Tools disponíveis

| Tool | Objetivo |
|---|---|
| `list_aws_profiles` | Mostra profiles permitidos, disponibilidade local e regiões |
| `list_domains` | Lista domínios por profile e região |
| `get_domain_config` | Lê configuração AWS do domínio |
| `get_cluster_health` | Saúde green/yellow/red |
| `get_cluster_stats` | Estatísticas gerais do cluster |
| `list_indices` | Índices, tamanho, documentos e shards |
| `get_index_details` | Settings, mappings, aliases e stats |
| `search_index` | Query DSL read-only com limites |
| `get_latest_documents` | Documentos mais recentes por timestamp |
| `get_field_mapping` | Tipo e conflito de mapping de um campo |
| `get_field_count` | Uso de `index.mapping.total_fields.limit` |
| `get_shard_allocation` | Distribuição e estado dos shards |
| `explain_unassigned_shard` | Motivo de shard não alocado |
| `get_disk_allocation` | Disco por nó |
| `get_cluster_settings` | Settings transient, persistent e default |
| `get_indexing_stats` | Indexação, busca, merges, refresh e segmentos |
| `get_pending_tasks` | Tarefas pendentes no cluster manager |
| `get_ingest_pipelines` | Pipelines de ingestão |
| `diagnose_cluster` | Diagnóstico consolidado de saúde, disco e flood stage |
| `diagnose_timestamp` | Min/max, mapping e amostras para dados antigos |

## Pré-requisitos

- Python 3.10 ou superior.
- `uv` recomendado.
- Profiles AWS já configurados em `~/.aws/config` e `~/.aws/credentials`.
- Rota de rede até o endpoint. Para domínio VPC-only, a máquina precisa estar na VPN, VPC ou em um túnel apropriado.

## Instalação

```bash
cd aws-opensearch-mcp
cp config.example.yaml config.yaml
uv sync --extra dev
```

Valide os profiles utilizados:

```bash
aws sts get-caller-identity --profile telemetry
aws opensearch list-domain-names --profile telemetry --region us-east-1
```

Quando o profile usa AWS SSO:

```bash
aws sso login --profile telemetry
```

## Rodar manualmente

```bash
AWS_OPENSEARCH_MCP_CONFIG="$PWD/config.yaml" \
AWS_SDK_LOAD_CONFIG=1 \
uv run aws-opensearch-mcp
```

O transporte padrão é `stdio`, portanto o processo aparentemente fica sem imprimir respostas no terminal. Isso é esperado: ele aguarda um cliente MCP.

## Configuração no Kiro

Use o arquivo de usuário `~/.kiro/settings/mcp.json` ou o arquivo do workspace `.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "aws-opensearch-readonly": {
      "command": "uv",
      "args": [
        "--directory",
        "/home/SEU_USUARIO/Projects/aws-opensearch-mcp",
        "run",
        "aws-opensearch-mcp"
      ],
      "env": {
        "AWS_OPENSEARCH_MCP_CONFIG": "/home/SEU_USUARIO/Projects/aws-opensearch-mcp/config.yaml",
        "AWS_SDK_LOAD_CONFIG": "1",
        "AWS_OPENSEARCH_MCP_LOG_LEVEL": "INFO"
      },
      "timeout": 120000
    }
  }
}
```

Evite `autoApprove` no primeiro uso. Depois de revisar os parâmetros e resultados, ferramentas puramente informativas, como `get_cluster_health`, podem ser aprovadas conforme a política do time.

## Testes

```bash
uv run pytest -q
uv run ruff check .
```

Para abrir no MCP Inspector:

```bash
uv run mcp dev mcp_server.py
```

## Exemplos de prompts no Kiro

```text
Use o profile telemetry em us-east-1 e liste os domínios OpenSearch disponíveis.
```

```text
No domínio logs-production, rode diagnose_cluster e explique apenas achados warning ou superiores.
```

```text
No índice sentinelone-*, verifique o mapping de @timestamp e diagnostique por que os documentos mais novos parecem ser de janeiro.
```

```text
Liste os 20 maiores índices e verifique quais estão próximos de index.mapping.total_fields.limit.
```

```text
Encontre shards não alocados e execute explain_unassigned_shard para o primeiro deles. Não faça alterações.
```

## Privacidade dos dados

As respostas das tools entram no contexto do cliente de IA. Restrinja `source_fields`, evite consultar documentos com dados pessoais desnecessários e use uma identidade com acesso somente aos índices necessários.

## IAM mínimo

O arquivo `examples/iam-policy.example.json` contém uma base. Ajuste conta, domínio e regiões.

A permissão `es:ESHttpPost` aparece porque APIs read-only como `_search` e `_cluster/allocation/explain` usam POST. O MCP não expõe endpoints arbitrários nem operações de escrita, mas a identidade AWS ainda deve seguir privilégio mínimo e, quando disponível, Fine-Grained Access Control do OpenSearch.

## Proteções implementadas

- Allowlist de profile e região.
- Validação de domínio, índice e campo.
- Bloqueio de path injection.
- Limite de documentos, bytes de query e resposta.
- Timeout em consultas.
- Bloqueio de `script`, `script_fields`, `runtime_mappings`, `rescore` e `stored_fields` nas queries fornecidas pelo modelo.
- Redação recursiva de tokens, senhas, cookies, chaves e segredos.
- Paginação e tamanhos internos de agregações limitados.
- Logs enviados para `stderr`, preservando o protocolo MCP em `stdout`.
- Produção e todos os demais profiles permanecem read-only nesta versão.

## Evolução sugerida

Uma segunda versão pode adicionar ferramentas de escrita estritamente específicas, sempre em pares `preview_*` e `apply_*`, com confirmação explícita e bloqueio por profile. Não adicione uma tool de request HTTP arbitrário, pois ela contornaria todas as proteções deste servidor.

## Referências oficiais

- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Amazon OpenSearch Service, assinatura SigV4: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/managedomains-signing-service-requests.html
- OpenSearch API: https://docs.opensearch.org/latest/api-reference/
- Kiro MCP configuration: https://kiro.dev/docs/mcp/configuration/
