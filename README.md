# LeitorSerialPro

Aplicação desktop em Python para leitura e análise de dados de portas seriais com recursos avançados de logging, firmware flashing e análise com IA.

## 🎯 Recursos Principais

- **Leitura em Tempo Real**: Captura dados de portas seriais COM com conexão automática e reconexão
- **Logging Automático**: Salva logs automaticamente em arquivo com timestamp
- **Busca e Filtro**: Pesquisa no log com destaque de resultados
- **Gravação de Firmware**: Interface para gravar firmware em dispositivos ESP com esptool
- **Análise com IA**: Analisa logs usando Google Gemini API e sugere comandos de resolução
- **Personalização**: Temas claro/escuro, fontes customizáveis e cores personalizáveis
- **Envio de Comandos**: Interface para enviar comandos diretos pela porta serial

## 📋 Pré-requisitos

- Python 3.8+
- Windows (adaptável para Linux/macOS)
- Porta serial disponível (USB/COM)

## 🚀 Instalação

### 1. Clone o repositório
```bash
git clone https://github.com/Thiago-taroliv/LeitorSerialPro.git
cd LeitorSerialPro
```

### 2. Crie um ambiente virtual
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

### 3. Instale as dependências
```bash
pip install -r requirements.txt
```

### 4. Execute a aplicação
```bash
python main.py
```

## 📦 Dependências

- **tkinter**: Interface gráfica (incluído com Python)
- **pyserial**: Comunicação com portas seriais
- **Pillow**: Processamento de imagens
- **esptool**: Gravação de firmware ESP (opcional, instalável via pip)
- **google-generativeai**: Análise com IA (opcional)

## 💻 Como Usar

### Leitura de Porta Serial
1. Selecione a porta na dropdown "Conexão"
2. Clique em "Iniciar" para começar a leitura
3. Os dados aparecem em tempo real na área de log

### Salvar Logs
- **Automático**: Habilite "Salvar automaticamente" na seção "Salvamento"
- **Manual**: Clique em "Salvar agora" para salvar o log atual

### Buscar no Log
1. Digite o termo na caixa "Pesquisar no log"
2. Clique em "Buscar" ou pressione Enter
3. Os resultados são destacados em amarelo

### Gravar Firmware
1. Clique em "Gravar firmware" na seção "Firmware"
2. Selecione a porta serial e o arquivo `.bin`
3. Configure o chip ESP (auto-detecta por padrão)
4. Clique em "Gravar firmware" e acompanhe o progresso

### Analisar com IA
1. Clique em "Analisador de Log (IA)"
2. Insira sua chave API do Google Gemini
3. Selecione o tipo de equipamento e contexto (opcional)
4. Clique em "Somente Analisar" ou "Analisar e Resolver"
5. A IA sugere um comando se solicitado

## 📁 Estrutura do Projeto

```
LeitorSerialPro/
├── main.py                          # Aplicação principal
├── requirements.txt                 # Dependências Python
├── build_exe.bat                    # Script para gerar executável
├── LeitorSerialPro.spec             # Configuração PyInstaller
├── serial_reader_settings.json      # Configurações salvas (gerado)
├── log_serial.txt                   # Log padrão (gerado)
├── media/                           # Assets (ícone, logo)
├── legacy_v1/                       # Versão anterior do projeto
└── build/                           # Arquivos de compilação (gerado)
```

## ⚙️ Configuração

As configurações são salvas automaticamente em `serial_reader_settings.json`:
- Tema (claro/escuro)
- Última porta usada
- Arquivo de log
- Fonte e tamanho
- Chave API Gemini
- Comandos e bins recentes

## 🔑 Variáveis de Ambiente

Para usar a análise com IA, você precisa:
1. Criar conta em [Google AI Studio](https://aistudio.google.com/)
2. Gerar uma chave API
3. Inserir a chave na interface do analisador de logs

## 📦 Gerar Executável

```bash
# Com PyInstaller
pyinstaller LeitorSerialPro.spec

# O executável será criado em dist/LeitorSerialPro.exe
```

## 🐛 Troubleshooting

| Problema | Solução |
|----------|---------|
| Porta não aparece | Verifique conexão USB, drivers do CH340/CP2102 |
| esptool não encontrado | Execute `pip install esptool` |
| Erro ao carregar logo | Certifique-se que a pasta `media/` existe |
| IA não funciona | Verifique chave API e conexão com internet |

## 📝 Licença

Projeto privado - Todos os direitos reservados

## 👤 Autor

**Thiago Oliveira**
- GitHub: [@Thiago-taroliv](https://github.com/Thiago-taroliv)

---

**Última atualização**: Junho 2026
