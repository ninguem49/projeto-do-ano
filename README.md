# Corte e Ação — Flask + PostgreSQL

Versão do projeto preparada para hospedagem com Flask e PostgreSQL.

## Rodar localmente

Requer Python 3.10+ e um banco PostgreSQL. Configure as variáveis de ambiente `DATABASE_URL` e `FLASK_SECRET_KEY`.

Crie um banco PostgreSQL e execute o conteúdo de `schema.sql` nele. Depois:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:5000`.

## Publicar no Render

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Adicione `DATABASE_URL` com a URL de conexão do PostgreSQL.
- Adicione `FLASK_SECRET_KEY` com uma chave longa e aleatória.

O Render fornece `PORT` automaticamente; o Gunicorn usa a porta disponibilizada pelo ambiente.

## Importante sobre arquivos enviados

Esta versão guarda anexos e fotos na pasta `uploads`. Em hospedagens com disco temporário, os arquivos podem desaparecer quando o serviço reiniciar ou for atualizado. Para manter anexos permanentemente, será necessário configurar armazenamento externo. Não use dados pessoais reais ou documentos sensíveis nesta demonstração escolar.

## Funcionalidades

Cadastro/login com senha protegida por hash, perfis, canais, mensagens, anexos, mensagens fixadas, busca, vagas, vagas salvas e candidaturas.

O chat atualiza por consulta periódica (polling), não por WebSocket. Esta é uma base de projeto escolar e ainda precisa de proteções adicionais antes de uso público amplo.
