# FinanCorp

Aplicativo de gestão financeira feito com Streamlit. Cada conta tem seu próprio espaço financeiro, com transações, categorias e relatórios separados.

## Recursos

- Dashboard, fluxo de caixa e contas a pagar e receber
- Cadastro e filtros de receitas e despesas
- Categorias e relatórios exportáveis em CSV
- Senhas protegidas com PBKDF2
- SQLite para uso local e PostgreSQL para hospedagem

## Executar no Windows

Instale Python 3.10 ou mais recente e execute run.bat.

## Publicar online

O projeto pode ser hospedado no Streamlit Community Cloud e usar PostgreSQL no Supabase. Publique app.py a partir do repositório e configure nos Secrets do Streamlit:

DEPLOYMENT_MODE = "cloud"
DATABASE_URL = "postgresql://..."

Use a URL de conexão real do seu projeto Supabase e mantenha-a privada. Nunca publique senha, .env, .streamlit/secrets.toml ou arquivos de banco. O arquivo financorp.db é local e ignorado pelo Git. Os dados locais não são transferidos automaticamente ao banco remoto.

Alterações enviadas ao GitHub podem atualizar o app publicado. Pessoas com acesso de escrita ao repositório podem modificar o código; os usuários do app só podem alterar os próprios dados.

## Limites gratuitos

O Streamlit Community Cloud pode suspender apps após 12 horas sem tráfego, e o Supabase Free pode pausar projetos com pouca atividade após 7 dias. Por isso, esta configuração gratuita não garante operação 24 horas por dia, todos os dias. Faça backups regulares dos dados importantes.

## Arquivos

- app.py: interface do aplicativo
- core.py: autenticação, isolamento de dados e acesso ao banco
- requirements.txt: dependências
- run.bat: inicialização local no Windows
