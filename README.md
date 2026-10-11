O MEU CONDOMÍNIO – Gestão financeira do condomínio


Projeto em linguagem Python e UI em pyQt6

Números de módulos: 24 (12 módulos gráficos e 12 módulos de dados)

Funcionalidades:

1. Seleção da conta do “ano corrente” ou do “histórico”

2. Dashboard com gráficos de Receitas, Despesas e do Balanço

3. Depósitos à Ordem

· importação do ficheiro CSV com os movimentos bancários

· classificação automática dos mesmos por contas, segundo os critérios estabelecidos na tabela de “configs” (regras importação)

· deteção e gravação dos movimentos de depósitos a prazo (poupança) na respetiva tabela

4. Depósitos a Prazo

· registo dos movimentos da conta corrente da poupança, manual ou automaticamente durante a importação do ficheiro da conta corrente

5. Caixa

· registo manual dos movimentos de caixa

6. Receitas

· calcula as Quotas normais e extras pagas e Juros recebidos durante o período

· controlo de quotas atrasadas

· apresentação das receitas em mapa PivotTable por meses

7. Despesas

· calcula despesas por contas

· apresentação em mapa PivotTable por meses

8. Balanço

· criação do balanço anual com os seguintes valores:

· saldo do ano anterior

· receitas do ano corrente

· despesas do ano corrente

· juros recebidos

· apuramento do saldo do exercício

· apuramento do saldo final

· geração de mapas de receitas, despesas e do balanço em Pdf

· geração de relatório em Pdf gerado por IA

9. Gestão de condóminos

· ficha de condóminos

· frações e andar

· opção de ativar/desativar condómino para envio de emails

· visualizar quotas pagas/por pagar de cada condómino por mês

· informação com totais anuais

· impressão do recibo em PDF

· seleção do administrador em funções

10. Documentos

· visualização de documentos (*.pdf, *.doc, *.xls) gravados na pasta “Docs”

· possibilidade de envio direto por email como anexo para todos os condóminos que estão ativos na ficha de condómino

11. Encerrar Ano

· cópia dos dados para a pasta de histórico

· encerramento do ano com passagem de saldos finais a saldos iniciais

· limpeza dos ficheiros para novo ano fiscal

12. Configurações

· Analisar ficheiro CSV do banco: analisa automaticamente a estrutura do ficheiro e grava os parâmetros na tabela configs para evitar erros na importação dos movimentos bancários por diferenças na estrutura do ficheiro

· manutenção da tabela configs e da tabela de contas

13. Ícone para abrir diretamente a app “Mailspring”, para se enviar e receber emails da conta Gmail do condomínio 42condominio@gmail.com sem se usar o browser
