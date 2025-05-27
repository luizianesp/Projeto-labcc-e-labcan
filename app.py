from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import bcrypt
import jwt
import datetime
from functools import wraps
import json

app = Flask(__name__)
CORS(app)

# Configurações
app.config['SECRET_KEY'] = 'sua_chave_secreta_aqui'
DATABASE = 'agendamento.db'

def get_db_connection():
    """Conecta ao banco de dados SQLite"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Para retornar resultados como dicionários
    return conn

def init_database():
    """Inicializa o banco de dados com as tabelas necessárias"""
    conn = get_db_connection()
    
    # Tabela de Professores
    conn.execute('''
        CREATE TABLE IF NOT EXISTS professores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_completo TEXT NOT NULL,
            matricula TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            telefone TEXT,
            departamento TEXT,
            senha_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de Laboratórios
    conn.execute('''
        CREATE TABLE IF NOT EXISTS laboratorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            localizacao TEXT NOT NULL,
            capacidade INTEGER NOT NULL,
            recursos TEXT, -- JSON string com lista de recursos
            status TEXT DEFAULT 'disponivel', -- disponivel, manutencao
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de Reservas
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id INTEGER NOT NULL,
            laboratorio_id INTEGER NOT NULL,
            data DATE NOT NULL,
            horario_inicio TIME NOT NULL,
            horario_fim TIME NOT NULL,
            disciplina TEXT NOT NULL,
            turma TEXT NOT NULL,
            descricao_atividade TEXT,
            status TEXT DEFAULT 'confirmada', -- confirmada, pendente, cancelada
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professor_id) REFERENCES professores (id),
            FOREIGN KEY (laboratorio_id) REFERENCES laboratorios (id)
        )
    ''')
    
    # Inserir dados iniciais se não existirem
    try:
        # Professores de exemplo
        senha_hash = bcrypt.hashpw('123456'.encode('utf-8'), bcrypt.gensalt())
        
        conn.execute('''
            INSERT OR IGNORE INTO professores 
            (nome_completo, matricula, email, telefone, departamento, senha_hash) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('Prof. André Gustavo', '123456', 'andre@uern.br', '(84) 99999-9999', 
              'Ciência da Computação', senha_hash))
        
        conn.execute('''
            INSERT OR IGNORE INTO professores 
            (nome_completo, matricula, email, telefone, departamento, senha_hash) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('Prof. Maria Silva', '123457', 'maria@uern.br', '(84) 88888-8888', 
              'Ciência da Computação', senha_hash))
        
        # Laboratórios de exemplo
        recursos_labcc = json.dumps(["30 Computadores", "Datashow", "Ar Condicionado", "Quadro Digital"])
        recursos_labcan = json.dumps(["25 Computadores", "Datashow", "Ar Condicionado"])
        
        conn.execute('''
            INSERT OR IGNORE INTO laboratorios 
            (nome, localizacao, capacidade, recursos, status) 
            VALUES (?, ?, ?, ?, ?)
        ''', ('LabCC', 'Bloco A - Sala 101', 30, recursos_labcc, 'disponivel'))
        
        conn.execute('''
            INSERT OR IGNORE INTO laboratorios 
            (nome, localizacao, capacidade, recursos, status) 
            VALUES (?, ?, ?, ?, ?)
        ''', ('LabCan', 'Campus Natal - Sala 201', 25, recursos_labcan, 'disponivel'))
        
        conn.commit()
    except Exception as e:
        print(f"Erro ao inserir dados iniciais: {e}")
    finally:
        conn.close()

def token_required(f):
    """Decorator para rotas que requerem autenticação"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'Token de acesso requerido'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expirado'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated

# ROTAS DA API

@app.route('/')
def index():
    """Página inicial - serve o frontend"""
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    """Rota de login para professores"""
    data = request.get_json()
    
    if not data or not data.get('matricula') or not data.get('senha'):
        return jsonify({'error': 'Matrícula e senha são obrigatórios'}), 400
    
    conn = get_db_connection()
    professor = conn.execute(
        'SELECT * FROM professores WHERE matricula = ?', 
        (data['matricula'],)
    ).fetchone()
    conn.close()
    
    if not professor:
        return jsonify({'error': 'Credenciais inválidas'}), 401
    
    # Verificar senha
    if bcrypt.checkpw(data['senha'].encode('utf-8'), professor['senha_hash']):
        # Gerar token JWT
        token = jwt.encode({
            'id': professor['id'],
            'matricula': professor['matricula'],
            'nome': professor['nome_completo'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'token': token,
            'professor': {
                'id': professor['id'],
                'nome': professor['nome_completo'],
                'matricula': professor['matricula'],
                'email': professor['email'],
                'departamento': professor['departamento']
            }
        })
    else:
        return jsonify({'error': 'Credenciais inválidas'}), 401

@app.route('/api/laboratorios', methods=['GET'])
@token_required
def get_laboratorios(current_user):
    """Listar laboratórios disponíveis"""
    conn = get_db_connection()
    laboratorios = conn.execute(
        'SELECT * FROM laboratorios WHERE status = "disponivel"'
    ).fetchall()
    conn.close()
    
    # Converter para lista de dicionários e fazer parse dos recursos
    result = []
    for lab in laboratorios:
        lab_dict = dict(lab)
        lab_dict['recursos'] = json.loads(lab_dict['recursos'] or '[]')
        result.append(lab_dict)
    
    return jsonify(result)

@app.route('/api/verificar-disponibilidade', methods=['POST'])
@token_required
def verificar_disponibilidade(current_user):
    """Verificar se um laboratório está disponível em determinado horário"""
    data = request.get_json()
    
    required_fields = ['laboratorio_id', 'data', 'horario_inicio', 'horario_fim']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Dados incompletos'}), 400
    
    conn = get_db_connection()
    
    # Verificar conflitos de horário
    conflitos = conn.execute('''
        SELECT * FROM reservas 
        WHERE laboratorio_id = ? 
        AND data = ? 
        AND status != 'cancelada'
        AND (
            (horario_inicio <= ? AND horario_fim > ?) OR
            (horario_inicio < ? AND horario_fim >= ?) OR
            (horario_inicio >= ? AND horario_fim <= ?)
        )
    ''', (
        data['laboratorio_id'], data['data'],
        data['horario_inicio'], data['horario_inicio'],
        data['horario_fim'], data['horario_fim'],
        data['horario_inicio'], data['horario_fim']
    )).fetchall()
    
    conn.close()
    
    return jsonify({
        'disponivel': len(conflitos) == 0,
        'conflitos': len(conflitos)
    })

@app.route('/api/reservas', methods=['POST'])
@token_required
def criar_reserva(current_user):
    """Criar nova reserva"""
    data = request.get_json()
    
    required_fields = ['laboratorio_id', 'data', 'horario_inicio', 'horario_fim', 'disciplina', 'turma']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Dados incompletos'}), 400
    
    conn = get_db_connection()
    
    # Verificar disponibilidade primeiro
    conflitos = conn.execute('''
        SELECT * FROM reservas 
        WHERE laboratorio_id = ? 
        AND data = ? 
        AND status != 'cancelada'
        AND (
            (horario_inicio <= ? AND horario_fim > ?) OR
            (horario_inicio < ? AND horario_fim >= ?) OR
            (horario_inicio >= ? AND horario_fim <= ?)
        )
    ''', (
        data['laboratorio_id'], data['data'],
        data['horario_inicio'], data['horario_inicio'],
        data['horario_fim'], data['horario_fim'],
        data['horario_inicio'], data['horario_fim']
    )).fetchall()
    
    if conflitos:
        conn.close()
        return jsonify({'error': 'Horário não disponível'}), 400
    
    # Inserir reserva
    try:
        cursor = conn.execute('''
            INSERT INTO reservas 
            (professor_id, laboratorio_id, data, horario_inicio, horario_fim, disciplina, turma, descricao_atividade, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmada')
        ''', (
            current_user['id'], data['laboratorio_id'], data['data'],
            data['horario_inicio'], data['horario_fim'], data['disciplina'],
            data['turma'], data.get('descricao_atividade', '')
        ))
        
        conn.commit()
        reserva_id = cursor.lastrowid
        conn.close()
        
        return jsonify({
            'message': 'Reserva criada com sucesso',
            'reserva_id': reserva_id
        }), 201
        
    except Exception as e:
        conn.close()
        return jsonify({'error': 'Erro ao criar reserva'}), 500

@app.route('/api/minhas-reservas', methods=['GET'])
@token_required
def get_minhas_reservas(current_user):
    """Listar reservas do professor logado"""
    conn = get_db_connection()
    
    reservas = conn.execute('''
        SELECT r.*, l.nome as laboratorio_nome, l.localizacao
        FROM reservas r
        JOIN laboratorios l ON r.laboratorio_id = l.id
        WHERE r.professor_id = ?
        ORDER BY r.data DESC, r.horario_inicio DESC
    ''', (current_user['id'],)).fetchall()
    
    conn.close()
    
    # Converter para lista de dicionários
    result = [dict(reserva) for reserva in reservas]
    return jsonify(result)

@app.route('/api/reservas/<int:reserva_id>/cancelar', methods=['PUT'])
@token_required
def cancelar_reserva(current_user, reserva_id):
    """Cancelar uma reserva"""
    conn = get_db_connection()
    
    # Verificar se a reserva pertence ao professor
    cursor = conn.execute('''
        UPDATE reservas 
        SET status = 'cancelada' 
        WHERE id = ? AND professor_id = ?
    ''', (reserva_id, current_user['id']))
    
    conn.commit()
    
    if cursor.rowcount == 0:
        conn.close()
        return jsonify({'error': 'Reserva não encontrada'}), 404
    
    conn.close()
    return jsonify({'message': 'Reserva cancelada com sucesso'})

@app.route('/api/dashboard', methods=['GET'])
@token_required
def get_dashboard(current_user):
    """Dados para o dashboard do professor"""
    conn = get_db_connection()
    
    # Total de reservas
    total_reservas = conn.execute(
        'SELECT COUNT(*) as total FROM reservas WHERE professor_id = ?',
        (current_user['id'],)
    ).fetchone()['total']
    
    # Reservas confirmadas
    reservas_confirmadas = conn.execute(
        'SELECT COUNT(*) as total FROM reservas WHERE professor_id = ? AND status = "confirmada"',
        (current_user['id'],)
    ).fetchone()['total']
    
    # Próximas reservas
    proximas_reservas = conn.execute('''
        SELECT r.*, l.nome as laboratorio_nome, l.localizacao
        FROM reservas r
        JOIN laboratorios l ON r.laboratorio_id = l.id
        WHERE r.professor_id = ? AND r.data >= date('now') AND r.status = 'confirmada'
        ORDER BY r.data ASC, r.horario_inicio ASC
        LIMIT 5
    ''', (current_user['id'],)).fetchall()
    
    conn.close()
    
    return jsonify({
        'totalReservas': total_reservas,
        'reservasConfirmadas': reservas_confirmadas,
        'proximasReservas': [dict(reserva) for reserva in proximas_reservas]
    })

if __name__ == '__main__':
    print("Inicializando banco de dados...")
    init_database()
    print("Banco de dados inicializado!")
    
    print("\nCredenciais de teste:")
    print("Matrícula: 123456, Senha: 123456 (Prof. André Gustavo)")
    print("Matrícula: 123457, Senha: 123456 (Prof. Maria Silva)")
    
    print(f"\nServidor rodando em http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)