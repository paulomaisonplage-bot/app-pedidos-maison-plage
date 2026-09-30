# Fotos de Obra · Maison Plage

App separado (dentro deste repositório) para organizar fotos tiradas pelos estagiários por **pavimento, dia e serviço**.

## Rodar
```bash
cd fotos_obra
pip install -r requirements.txt
FOTOS_USERS="ana:senha1,joao:senha2" FOTOS_SECRET="texto-longo-aleatorio" uvicorn main:app --port 8001
```
- `FOTOS_USERS`: usuários da equipe (`nome:senha,nome:senha`). Sem isso, vale `admin:admin` (só testes).
- `FOTOS_SECRET`: assina a sessão; defina um valor fixo em produção.
- `FOTOS_DIR`: pasta de armazenamento (padrão `fotos_obra/storage`, ignorada pelo git).

Fotos ficam em `storage/originais/<Pavimento>/<AAAA-MM-DD>/<Servico>/`. O botão **Baixar ZIP** gera a mesma estrutura para guardar no desktop.
Atenção: no plano free do Render o disco é apagado a cada reinício; para produção use disco persistente ou outro armazenamento.
