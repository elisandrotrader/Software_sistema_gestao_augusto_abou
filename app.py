import sqlite3
from flask import Flask, render_template, request, redirect, url_for, jsonify,make_response
import datetime
import csv
import os
import io
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import letter
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport import requests

app = Flask(__name__)

# Configuração do Banco de Dados SQLite
def init_db():
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS estoque (
                 id INTEGER PRIMARY KEY,
                 produto TEXT,
                 codigo_barras TEXT,
                 quantidade INTEGER,
                 validade DATE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
                 id INTEGER PRIMARY KEY,
                 regiao TEXT,
                 cidade TEXT,
                 num_loja TEXT,
                 potencia_loja TEXT,
                 num_cim TEXT,
                 endereco TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS auditoria (
                 id INTEGER PRIMARY KEY,
                 acao TEXT,
                 data TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS entradas (
                 id INTEGER PRIMARY KEY,
                 produto_id INTEGER,
                 quantidade INTEGER,
                 data TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS saidas (
                 id INTEGER PRIMARY KEY,
                 produto_id INTEGER,
                 quantidade INTEGER,
                 cliente_id INTEGER,
                 data TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fornecedores (
                 fornecedor_id INTEGER PRIMARY KEY,
                 fornecedor_regiao TEXT,
                 fornecedor_cidade TEXT,
                 fornecedor_num_loja TEXT,
                 fornecedor_potencia_loja TEXT,
                 fornecedor_num_cim TEXT,
                 fornecedor_endereco TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Função para log de auditoria
def log_auditoria(acao):
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("INSERT INTO auditoria (acao, data) VALUES (?, ?)", (acao, datetime.datetime.now()))
    conn.commit()
    conn.close()

# Configuração da API do Google Drive 
SCOPES = ['https://www.googleapis.com/auth/drive.file']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'

def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(requests.Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

# Rotas
@app.route('/')
def index():
    return render_template('/index.html')

@app.route('/estoque', methods=['GET', 'POST'])
def estoque():
    if request.method == 'POST':
        produto = request.form['produto']
        codigo_barras = request.form['codigo_barras']
        quantidade = int(request.form['quantidade'])
        validade = request.form['validade']
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        c.execute("INSERT INTO estoque (produto, codigo_barras, quantidade, validade) VALUES (?, ?, ?, ?)", 
                  (produto, codigo_barras, quantidade, validade))
        produto_id = c.lastrowid
        c.execute("INSERT INTO entradas (produto_id, quantidade, data) VALUES (?, ?, ?)", 
                  (produto_id, quantidade, datetime.datetime.now()))
        conn.commit()
        conn.close()
        log_auditoria(f"Entrada de produto: {produto} (ID: {produto_id})")
        return redirect(url_for('estoque'))
    # --- LÓGICA DE BUSCA APRIMORADA ---
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    
    # Busca todos os itens (para a tabela principal)
    c.execute("SELECT * FROM estoque ORDER BY validade ASC")
    itens = c.fetchall()

    # Busca apenas itens que vencerão nos próximos 30 dias (e que ainda não venceram)
    data_hoje = datetime.date.today()
    data_limite = data_hoje + datetime.timedelta(days=30)
    c.execute("SELECT * FROM estoque WHERE validade BETWEEN ? AND ? ORDER BY validade ASC", 
              (data_hoje.strftime('%Y-%m-%d'), data_limite.strftime('%Y-%m-%d')))
    vencimento_proximo = c.fetchall()

    # Busca apenas itens já vencidos
    c.execute("SELECT * FROM estoque WHERE validade < ? ORDER BY validade ASC", (data_hoje.strftime('%Y-%m-%d'),))
    vencidos = c.fetchall()
    
    conn.close()
    
    # Passa as três listas para o template
    return render_template('estoque.html', 
                           itens=itens, 
                           vencidos=vencidos, 
                           vencimento_proximo=vencimento_proximo)

#Editar Itens do Estoque
@app.route('/estoque/editar/<int:id>', methods=['GET', 'POST'])
def editar_item(id):
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()

    if request.method == 'POST':
        produto = request.form['produto']
        codigo_barras = request.form['codigo_barras']
        quantidade = int(request.form['quantidade'])
        validade = request.form['validade']

        c.execute('''UPDATE estoque SET produto=?, codigo_barras=?, quantidade=?, validade=? WHERE id=?''',
                  (produto, codigo_barras, quantidade, validade, id))
        conn.commit()
        conn.close()
        log_auditoria(f"Item de estoque atualizado: {produto} (ID: {id})")
        return redirect(url_for('estoque'))

    # Se o método for GET, busca o item e mostra o formulário de edição
    c.execute("SELECT * FROM estoque WHERE id = ?", (id,))
    item = c.fetchone()
    conn.close()
    return render_template('editar_item.html', item=item)

#Excluir Itens do Estoque
@app.route('/estoque/delete/<int:id>')
def deletar_item(id):
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("DELETE FROM estoque WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    log_auditoria(f"Item de estoque excluído: ID {id}")
    return redirect(url_for('estoque'))

#Relatórios de Estoque em PDF
@app.route('/relatorio/estoque/pdf')
def relatorio_estoque_pdf():
    # Conectar ao banco e buscar dados do estoque
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("SELECT id, produto, codigo_barras, quantidade, validade FROM estoque ORDER BY produto")
    itens = c.fetchall()
    conn.close()

    # Gerar PDF em memória
    buffer = io.BytesIO()

    # Cria o canvas do pdf especificando o tamanho da página
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # 3. "Desenhar" o conteúdo no PDF
    # ReportLab usa um sistema de coordenadas onde (0,0) é o canto inferior esquerdo.
    # A página 'letter' tem 612 pontos de largura e 792 de altura.
    
    # Título do relatório
    p.setFont("Helvetica", 12)
    p.drawString(1 * inch, height - 1 * inch, "Relatório de Estoque")
    y = height - 1.5 * inch
    p.setFont("Helvetica", 10)
    for item in itens:
        print(item)
        print(len(item))
        linha = f"ID: {item[0]}, Produto: {item[1]}, Código de Barras: {item[2]}, Quantidade: {item[3]}, Validade: {item[4]}"
        p.drawString(1 * inch, y, linha)
        y -= 0.25 * inch
        if y < 1 * inch:
            p.showPage()
            p.setFont("Helvetica", 10)
            y = height - 1 * inch
    #Finaliza o PDF
    p.save()
    buffer.seek(0)# Volta para o inicio do buffer

    #cria a resposta do Flask com o PDF
    # Cria a resposta do Flask
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=relatorio_estoque.pdf'

    return response

@app.route('/saida', methods=['GET', 'POST'])
def saida():
    if request.method == 'POST':
        codigo_barras = request.form['codigo_barras']
        quantidade = int(request.form['quantidade'])
        cliente_id = int(request.form['cliente_id'])
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        # Verifica cliente existe
        c.execute("SELECT id FROM clientes WHERE id = ?", (cliente_id,))
        if not c.fetchone():
            conn.close()
            return "Cliente não encontrado!", 400
        # Busca produto por codigo_barras
        c.execute("SELECT id, quantidade FROM estoque WHERE codigo_barras = ?", (codigo_barras,))
        produto = c.fetchone()
        if not produto or produto[1] < quantidade:
            conn.close()
            return "Produto não encontrado ou estoque insuficiente!", 400
        produto_id = produto[0]
        # Atualiza estoque
        c.execute("UPDATE estoque SET quantidade = quantidade - ? WHERE id = ?", (quantidade, produto_id))
        # Registra saida
        c.execute("INSERT INTO saidas (produto_id, quantidade, cliente_id, data) VALUES (?, ?, ?, ?)", 
                  (produto_id, quantidade, cliente_id, datetime.datetime.now()))
        conn.commit()
        conn.close()
        log_auditoria(f"Saída de produto ID {produto_id} para cliente {cliente_id}")
        return redirect(url_for('saida'))
    return render_template('saida.html')

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
    if request.method == 'POST':
        regiao = request.form['regiao']
        cidade = request.form['cidade']
        num_loja = request.form['num_loja']
        potencia_loja = request.form['potencia_loja']
        num_cim = request.form['num_cim']
        endereco = request.form['endereco']
        if not all([regiao, cidade, num_loja, potencia_loja, num_cim, endereco]):
            return "Campos obrigatórios faltando!", 400
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        c.execute("INSERT INTO clientes (regiao, cidade, num_loja, potencia_loja, num_cim, endereco) VALUES (?, ?, ?, ?, ?, ?)",
                  (regiao, cidade, num_loja, potencia_loja, num_cim, endereco))
        conn.commit()
        conn.close()
        log_auditoria(f"Cadastrado cliente: {num_loja}")
        return redirect(url_for('clientes'))
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("SELECT * FROM clientes")
    clientes_list = c.fetchall()
    conn.close()
    return render_template('clientes.html', clientes=clientes_list)

@app.route('/fornecedores', methods=['GET', 'POST'])
def fornecedores():
    if request.method == 'POST':
        regiao = request.form['fornecedor_regiao']
        cidade = request.form['fornecedor_cidade']
        num_loja = request.form['fornecedor_num_loja']
        potencia_loja = request.form['fornecedor_potencia_loja']
        num_cim = request.form['fornecedor_num_cim']
        endereco = request.form['fornecedor_endereco']
        if not all([regiao, cidade, num_loja, potencia_loja, num_cim, endereco]):
            return "Campos obrigatórios faltando!", 400
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        c.execute("INSERT INTO fornecedores (fornecedor_regiao, fornecedor_cidade, fornecedor_num_loja, fornecedor_potencia_loja, fornecedor_num_cim, fornecedor_endereco) VALUES (?, ?, ?, ?, ?, ?)",
                  (regiao, cidade, num_loja, potencia_loja, num_cim, endereco))
        conn.commit()
        conn.close()
        log_auditoria(f"Cadastrado fornecedor: {num_loja}")
        return redirect(url_for('fornecedores'))
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("SELECT * FROM fornecedores")
    fornecedores_list = c.fetchall()
    conn.close()
    return render_template('fornecedores.html', fornecedores=fornecedores_list)

@app.route('/auditoria')
def auditoria():
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("SELECT * FROM auditoria ORDER BY data DESC")
    logs = c.fetchall()
    conn.close()
    return render_template('auditoria.html', logs=logs)

@app.route('/export_auditoria')
def export_auditoria():
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("SELECT * FROM auditoria")
    logs = c.fetchall()
    conn.close()
    with open('auditoria.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Ação', 'Data'])
        writer.writerows(logs)
    return "Exportado para auditoria.csv"

# Relatórios
@app.route('/relatorio_entradas', methods=['GET', 'POST'])
def relatorio_entradas():
    if request.method == 'POST':
        data_inicio = request.form['data_inicio']
        data_fim = request.form['data_fim']
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        c.execute('''SELECT e.id, est.produto, e.quantidade, e.data 
                     FROM entradas e JOIN estoque est ON e.produto_id = est.id 
                     WHERE e.data BETWEEN ? AND ?''', (data_inicio, data_fim))
        dados = c.fetchall()
        conn.close()
        return render_template('relatorio.html', titulo='Relatório de Entradas', dados=dados, colunas=['ID', 'Produto', 'Quantidade', 'Data'])
    return render_template('form_periodo.html', tipo='entradas')

@app.route('/relatorio_saidas', methods=['GET', 'POST'])
def relatorio_saidas():
    if request.method == 'POST':
        data_inicio = request.form['data_inicio']
        data_fim = request.form['data_fim']
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        c.execute('''SELECT s.id, est.produto, s.quantidade, s.data 
                     FROM saidas s JOIN estoque est ON s.produto_id = est.id 
                     WHERE s.data BETWEEN ? AND ?''', (data_inicio, data_fim))
        dados = c.fetchall()
        conn.close()
        return render_template('relatorio.html', titulo='Relatório de Saídas', dados=dados, colunas=['ID', 'Produto', 'Quantidade', 'Data'])
    return render_template('form_periodo.html', tipo='saidas')

@app.route('/relatorio_saidas_clientes', methods=['GET', 'POST'])
def relatorio_saidas_clientes():
    if request.method == 'POST':
        data_inicio = request.form['data_inicio']
        data_fim = request.form['data_fim']
        conn = sqlite3.connect('gestao.db')
        c = conn.cursor()
        c.execute('''SELECT s.id, est.produto, s.quantidade, c.num_loja AS cliente, s.data 
                     FROM saidas s JOIN estoque est ON s.produto_id = est.id 
                     JOIN clientes c ON s.cliente_id = c.id 
                     WHERE s.data BETWEEN ? AND ?''', (data_inicio, data_fim))
        dados = c.fetchall()
        conn.close()
        return render_template('relatorio.html', titulo='Relatório de Saídas por Clientes', dados=dados, colunas=['ID', 'Produto', 'Quantidade', 'Cliente', 'Data'])
    return render_template('form_periodo.html', tipo='saidas_clientes')

@app.route('/backup_nuvem')
def backup_nuvem():
    try:
        service = get_drive_service()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_metadata = {'name': f'gestao_backup_{timestamp}.db'}
        media = MediaFileUpload('gestao.db', mimetype='application/octet-stream')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        log_auditoria(f"Backup realizado no Google Drive: {file.get('id')}")
        return "Backup realizado com sucesso no Google Drive!"
    except Exception as e:
        return f"Erro no backup: {str(e)} (Verifique conexão e credentials.json)"

# Editar Clientes
@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
def editar_cliente(id):
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()

    if request.method == 'POST':
        # Pega TODOS os campos do formulário de EDIÇÃO
        regiao = request.form['regiao']
        cidade = request.form['cidade']
        num_loja = request.form['num_loja']
        potencia_loja = request.form['potencia_loja']
        num_cim = request.form['num_cim']
        endereco = request.form['endereco']

        c.execute('''UPDATE clientes SET regiao=?, cidade=?, num_loja=?, potencia_loja=?, num_cim=?, endereco=? 
                     WHERE id=?''', 
                  (regiao, cidade, num_loja, potencia_loja, num_cim, endereco, id))
        conn.commit()
        conn.close()
        log_auditoria(f"Cliente atualizado: Loja {num_loja}")
        return redirect(url_for('clientes'))

    # Se o método for GET, busca o cliente e mostra o formulário de edição
    c.execute("SELECT * FROM clientes WHERE id = ?", (id,))
    cliente = c.fetchone()
    conn.close()
    return render_template('editar_cliente.html', cliente=cliente)

# Editar Fornecedores
@app.route('/fornecedores/editar/<int:id>', methods=['GET', 'POST'])
def editar_fornecedores(id):
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()

    if request.method == 'POST':
        regiao = request.form['fornecedor_regiao']
        cidade = request.form['fornecedor_cidade']
        num_loja = request.form['fornecedor_num_loja']
        potencia_loja = request.form['fornecedor_potencia_loja']
        num_cim = request.form['fornecedor_num_cim']
        endereco = request.form['fornecedor_endereco']
        c.execute('''UPDATE fornecedores SET fornecedor_regiao=?, fornecedor_cidade=?, fornecedor_num_loja=?, fornecedor_potencia_loja=?, fornecedor_num_cim=?, fornecedor_endereco=? WHERE fornecedor_id=?''',
                  (regiao, cidade, num_loja, potencia_loja, num_cim, endereco, id))
        conn.commit()
        conn.close()
        log_auditoria(f"Fornecedor atualizado: {num_loja} (ID: {id})")
        return redirect(url_for('fornecedores'))

    # Se o método for GET, busca o fornecedor e mostra o formulário de edição
    c.execute("SELECT * FROM fornecedores WHERE fornecedor_id = ?", (id,))
    fornecedor = c.fetchone()
    conn.close()
    return render_template('editar_fornecedores.html', fornecedor=fornecedor)

#Excluir Fornecedores
@app.route('/fornecedores/delete/<int:id>')
def deletar_fornecedores(id):
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("DELETE FROM fornecedores WHERE fornecedor_id = ?", (id,))
    conn.commit()
    conn.close()
    log_auditoria(f"Fornecedores excluído: ID {id}")
    return redirect(url_for('fornecedores'))
    


#Excluir Clientes
@app.route('/cliente/delete/<int:id>')
def delete_cliente(id):
    # Esta rota SÓ lida com a exclusão
    conn = sqlite3.connect('gestao.db')
    c = conn.cursor()
    c.execute("DELETE FROM clientes WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    
    log_auditoria(f"Cliente excluído: ID {id}")
    
    return redirect(url_for('clientes'))


if __name__ == '__main__':
    import webbrowser
    url = 'http://127.0.0.1:5000/'
    webbrowser.open(url)
    app.run(debug=False)