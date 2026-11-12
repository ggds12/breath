# TokenBar

Painel local para acompanhar os limites de uso do **Claude** (assinatura Pro/Max) e do **Codex** (assinatura ChatGPT), com a identidade visual GGDS.

- **Sessão (5h)** e **Semana**, em %, com horário de reinício e um marcador de ritmo: onde você estaria se usasse a cota de forma uniforme.
- Limites semanais por modelo, quando a Anthropic os informa (ex.: "Semana · Opus").
- **Tokens por dia** nos últimos 7 dias, contados nos logs locais do Claude Code e do Codex.
- O mascote GGDS muda de estado conforme a situação: pronto, atenção, limite atingido, sem dados.
- Tema claro e escuro, atalhos `R` (atualizar) e `T` (tema). O título da aba resume as sessões (`Claude 22% · Codex 100%`).

> Nem o Claude nem o Codex têm limite "diário". Os dois usam uma janela móvel de **5 horas** (sessão) e uma janela de **7 dias** (semana). O consumo diário aparece na seção *Tokens por dia*.

## Requisitos

- Windows 10/11 (funciona em macOS/Linux, mas os scripts de atalho são para Windows)
- Python 3.10+. **Nenhuma dependência externa.** Só a biblioteca padrão.
- Claude Code logado com a sua assinatura (`claude`) e/ou Codex logado com a conta ChatGPT.

## Uso

```bash
python -m tokenbar
```

Abra <http://127.0.0.1:7878>. Ou use os scripts:

```powershell
# abre como app (janela própria do Edge), iniciando o servidor em segundo plano
powershell -ExecutionPolicy Bypass -File scripts\start.ps1

# cria atalhos na Área de Trabalho e no Menu Iniciar (adicione -AoIniciar para abrir com o Windows)
powershell -ExecutionPolicy Bypass -File scripts\instalar-atalho.ps1

# encerra o servidor
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

### Configuração (variáveis de ambiente)

| Variável | Padrão | Para quê |
|---|---|---|
| `TOKENBAR_PORT` | `7878` | Porta local |
| `TOKENBAR_LIMITS_TTL` | `60` | Segundos entre consultas às APIs de uso |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Pasta do Claude Code |
| `CODEX_HOME` | `~/.codex` | Pasta do Codex |

## De onde vêm os números

| Fonte | O que lê | Rede |
|---|---|---|
| Claude, limites | `GET https://api.anthropic.com/api/oauth/usage` com o token OAuth de `~/.claude/.credentials.json` | Só Anthropic |
| Codex, limites | `GET https://chatgpt.com/backend-api/wham/usage` com o token de `~/.codex/auth.json` | Só OpenAI |
| Codex, sem rede | Último `rate_limits` nos logs `~/.codex/sessions/**/rollout-*.jsonl` | Nenhuma |
| Tokens por dia | `~/.claude/projects/**/*.jsonl` e os logs de sessão do Codex | Nenhuma |

Esses endpoints de uso não são APIs públicas documentadas: são os mesmos que o Claude Code e o Codex usam para mostrar os limites. Se mudarem, o Codex continua funcionando pelos logs locais, e o painel indica a falha no cartão do provedor.

## Segurança

Veja [SECURITY.md](SECURITY.md). Em resumo: o servidor escuta só em `127.0.0.1`, os tokens nunca chegam ao navegador, os arquivos de credenciais são **somente leitura** (o TokenBar nunca renova nem regrava tokens) e as únicas saídas de rede são `api.anthropic.com` e `chatgpt.com`.

## Testes

```bash
python -m unittest discover -s tests -v
```

## Estrutura

```
tokenbar/            servidor e coletores (Python, só stdlib)
  providers/         claude.py, codex.py
  localusage.py      tokens por dia a partir dos logs locais
  net.py             cliente HTTPS com lista de hosts permitidos
  server.py          HTTP local, API /api/status, cabeçalhos de segurança
web/                 painel (HTML, CSS e JS sem framework) e assets da marca
scripts/             start / stop / atalhos para Windows
tests/
```

## Licença

Código sob MIT. Marca, mascote, símbolo e ícones GGDS (`web/assets/`, exceto as fontes) © Gustavo Gomes dos Santos, todos os direitos reservados. As fontes Inter e JetBrains Mono seguem a SIL OFL (licenças em `web/assets/fonts/`).
