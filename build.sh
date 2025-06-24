#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Instalando dependências..."
pip install -r requirements.txt

echo "Coletando arquivos estáticos..."
python siteDjangoProject/manage.py collectstatic --no-input

echo "Executando migrações..."
python siteDjangoProject/manage.py migrate

echo "Build concluído!"