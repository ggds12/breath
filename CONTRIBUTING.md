# Como contribuir com o Breath

Obrigado pelo interesse! Toda contribuição entra por **pull request**: ninguém publica direto na `main`.

## Fluxo

1. Faça um **fork** do repositório e crie uma branch a partir da `main` (`git switch -c minha-melhoria`).
2. Faça a mudança, com testes quando fizer sentido.
3. Rode localmente:
   ```powershell
   python -m unittest discover -s tests -v
   python -m breath --show      # confira na tela
   ```
4. Abra o pull request preenchendo o modelo (o que muda, como testou, checklist de segurança).
5. O **CI** roda os testes no Windows e no Linux. O PR só pode entrar com o check **validacao** verde.
6. O mantenedor revisa. Pedidos de ajuste e conversas precisam ser resolvidos antes do merge.

PRs de quem contribui pela primeira vez só rodam o CI depois que o mantenedor libera; isso é normal.

## Regras do projeto

- **Sem dependências obrigatórias.** O Breath roda só com a biblioteca padrão do Python. Bibliotecas para recursos específicos de um sistema (ex.: o ícone no macOS) entram como opcionais em `pyproject.toml`.
- **Privacidade primeiro.** Nada sai da máquina, a não ser a consulta ao serviço da própria conta. Chaves e tokens nunca vão para o navegador, para o log, para arquivos de texto ou para os testes.
- **Números só de fontes documentadas.** Para acompanhar uma nova IA, use o endpoint oficial de uso ou saldo e cite a documentação no PR.
- **Interface em português**, com a mesma identidade visual (gerada por `tools/make_brand.py`).
- **Commits pequenos e com mensagens claras.**

## Segurança

Achou uma falha? **Não abra uma issue pública.** Use **Security → Report a vulnerability** neste repositório. O modelo de segurança está em [SECURITY.md](SECURITY.md).
