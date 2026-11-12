# TokenBar

Painel local para acompanhar os limites de uso do **Claude** (assinatura Pro/Max) e do **Codex** (assinatura ChatGPT), com a identidade visual GGDS.

- **Sessão (5h)** e **Semana** em barras animadas, com horário e contagem regressiva do reinício e um marcador de ritmo: onde você estaria se usasse a cota de forma uniforme.
- Limites semanais por modelo, quando a Anthropic os informa (ex.: "Semana · Opus").
- O mascote GGDS animado muda de estado conforme a situação: pronto, buscando, atualizando, concluído, atenção, limite atingido, sem dados e em repouso.
- Interface em camadas 3D que acompanham o ponteiro, fundo vivo, entrada em cascata e números que contam até o valor. Respeita "reduzir movimento" do Windows.
- Tema claro e escuro, atalhos `R` (atualizar), `T` (tema), `F` (fixar) e `Esc` (fechar).

> Nem o Claude nem o Codex têm limite "diário". Os dois usam uma janela móvel de **5 horas** (sessão) e uma janela de **7 dias** (semana).

## Requisitos

- Windows 10/11 (funciona em macOS/Linux, mas os scripts de atalho são para Windows)
- Python 3.10+. **Nenhuma dependência externa.** Só a biblioteca padrão.
- Claude Code logado com a sua assinatura (`claude`) e/ou Codex logado com a conta ChatGPT.

## Uso

O TokenBar fica nos **ícones ocultos** da barra de tarefas (a setinha `^` ao lado do relógio).

- **Clique esquerdo no ícone:** abre ou fecha a janelinha com os limites, junto ao relógio. Ela fecha sozinha quando você clica fora ou aperta `Esc`. O alfinete (ou `F`) a mantém aberta.
- **Clique direito:** Abrir, Painel completo no navegador, Atualizar agora e Sair.
- **Passar o mouse:** a dica mostra o uso atual, ex.: `TokenBar · Claude 22% (sem. 78%) · Codex 100% (sem. 16%)`.
- **Notificação do Windows** quando uma janela passa de 80% ou chega a 100%.

```powershell
# inicia (ícone + janelinha)
powershell -ExecutionPolicy Bypass -File scripts\start.ps1

# atalhos no Menu Iniciar e na Área de Trabalho; -AoIniciar inicia junto com o Windows
powershell -ExecutionPolicy Bypass -File scripts\instalar-atalho.ps1 -AoIniciar

# remove os atalhos
powershell -ExecutionPolicy Bypass -File scripts\instalar-atalho.ps1 -Remover

# encerra (o mesmo que "Sair" no menu do ícone)
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

Sem ícone, só o servidor: `python -m tokenbar --no-tray` e abra <http://127.0.0.1:7878>.

A janelinha é o Microsoft Edge em modo app, com um perfil separado em `%LOCALAPPDATA%\TokenBar\janela` (não usa seus favoritos, senhas ou cookies). O TokenBar recorta só a área da página, então não há barra de título. Também tira a janela da barra de tarefas e do Alt+Tab e a mantém por cima, no canto do relógio, como um menu do Windows.

### Configuração (variáveis de ambiente)

| Variável | Padrão | Para quê |
|---|---|---|
| `TOKENBAR_PORT` | `7878` | Porta local |
| `TOKENBAR_LIMITS_TTL` | `60` | Segundos entre consultas às APIs de uso |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Pasta do Claude Code |
| `CODEX_HOME` | `~/.codex` | Pasta do Codex |

A última leitura boa fica em `%LOCALAPPDATA%\TokenBar\ultima-leitura.json` (só porcentagens e horários), para a janelinha abrir já com dados e continuar mostrando algo se um provedor recusar uma consulta.

## De onde vêm os números

| Fonte | O que lê | Rede |
|---|---|---|
| Claude, limites | `GET https://api.anthropic.com/api/oauth/usage` com o token OAuth de `~/.claude/.credentials.json` | Só Anthropic |
| Codex, limites | `GET https://chatgpt.com/backend-api/wham/usage` com o token de `~/.codex/auth.json` | Só OpenAI |
| Codex, sem rede | Último `rate_limits` nos logs `~/.codex/sessions/**/rollout-*.jsonl` | Nenhuma |

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
  net.py             cliente HTTPS com lista de hosts permitidos
  server.py          HTTP local, API /api/status, cabeçalhos de segurança
  tray.py            ícone na bandeja do Windows (ctypes/Win32, sem dependências)
web/                 painel (HTML, CSS e JS sem framework) e assets da marca
scripts/             start / stop / atalhos para Windows
tests/
```

## Licença

Código sob MIT. Marca, mascote, símbolo e ícones GGDS (`web/assets/`, exceto as fontes) © Gustavo Gomes dos Santos, todos os direitos reservados. As fontes Inter e JetBrains Mono seguem a SIL OFL (licenças em `web/assets/fonts/`).
