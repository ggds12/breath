# Modelo de segurança

O TokenBar foi feito para uma pessoa, numa máquina. O objetivo é que nada do que ele lê saia do computador, exceto as consultas de uso feitas aos próprios provedores, com o token que já pertence a eles.

## O que ele lê

| Arquivo | Uso | Escrita |
|---|---|---|
| `~/.claude/.credentials.json` | `accessToken` para consultar o uso na Anthropic | **Nunca** |
| `~/.codex/auth.json` | `access_token` e `account_id` para consultar o uso no ChatGPT | **Nunca** |
| `~/.codex/sessions/**/rollout-*.jsonl` | Último `rate_limits` (plano B offline do Codex) | Nunca |
| `%LOCALAPPDATA%\TokenBar\ultima-leitura.json` | Última leitura boa (porcentagens, horários, rótulos e plano; nenhum token, e-mail ou ID) | Sim, pelo TokenBar |

O TokenBar **não renova** tokens. A renovação giraria o refresh token e poderia deslogar o Claude Code ou o Codex. Quando um token expira, o painel pede para você abrir a ferramenta correspondente, que renova sozinha.

## Defesas no servidor local

- Escuta apenas em `127.0.0.1`. Não é configurável, para não expor a porta na rede por engano.
- **Host** precisa ser `127.0.0.1:<porta>` ou `localhost:<porta>`, o que bloqueia DNS rebinding.
- A API exige o cabeçalho `X-TokenBar: 1` e recusa `Origin` externo. Um site aberto no navegador não consegue mandar esse cabeçalho sem um preflight CORS, e o servidor nunca aprova preflights (`OPTIONS` → 405).
- Somente `GET`/`HEAD`. Não há endpoint que grave ou execute algo.
- Arquivos estáticos só de `web/`, com extensões permitidas e proteção contra `../`.
- Cabeçalhos: CSP `default-src 'none'` sem inline, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, COOP/CORP.
- A resposta da API traz só percentuais, horários e contagens. Tokens, e-mail e IDs de conta são descartados no servidor.
- O log registra só método, caminho e status, sem query string nem cabeçalhos.

## Defesas na saída de rede

- HTTPS com verificação de certificado do sistema.
- Lista fixa de hosts: `api.anthropic.com` e `chatgpt.com`. Qualquer outro é recusado.
- Redirecionamentos são bloqueados, então o cabeçalho `Authorization` nunca é reenviado a outro host.
- Respostas limitadas a 1 MB. Consultas com cache de 60 s; atualização manual no máximo a cada 15 s.

## Cadeia de suprimentos

Nenhuma dependência de terceiros: só a biblioteca padrão do Python e arquivos estáticos locais (sem CDN, sem fontes externas, sem analytics).

## Limites conhecidos

- Qualquer programa rodando com o seu usuário do Windows consegue ler os mesmos arquivos de credenciais. O TokenBar não piora isso, mas também não protege contra malware local.
- Os endpoints de uso não são públicos nem documentados e podem mudar sem aviso.
