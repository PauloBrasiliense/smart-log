import streamlit as st
import re
import pandas as pd
import sqlparse

st.set_page_config(page_title="Visualizador de Logs", layout="wide")
st.title("📜 Visualizador de Logs com Tabela")

uploaded_file = st.file_uploader("Escolha um arquivo de log (.txt ou .log)", type=["txt", "log"])

if uploaded_file:
    try:
        log_data = uploaded_file.read().decode("utf-8")
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        log_data = uploaded_file.read().decode("latin1")

    log_lines = log_data.splitlines()

    entry_pattern = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}) - (\d{6}) (.*?)$")
    legacy_entry_pattern = re.compile(r"^\d{6} \d{2}:\d{2}:\d{2} ")

    current_block = []
    blocks = []

    for line in log_lines:
        if ("Log Iniciado Por:" in line or
            re.search(r"Por: \\\\totvs\\\\Hoteis\\\\", line, re.IGNORECASE) or
            re.search(r"\\\\totvs\\\\Hoteis\\\\.*\\.exe", line, re.IGNORECASE)):
            continue

        if entry_pattern.match(line) or legacy_entry_pattern.match(line):
            if current_block:
                blocks.append(current_block)
                current_block = []
        current_block.append(line)
    if current_block:
        blocks.append(current_block)

    def parse_block(block):
        sql_lines = []
        fetch_rows = []
        current_row = {}
        is_sql_block = False
        record_count = None
        has_error = False
        error_line = None

        for line in block:
            if "Open:" in line or "Erro:" in line:
                is_sql_block = True
                sql_lines = []
                clean_line = re.sub(r"^(.*?)(Open:|Erro:)\s*", "", line).strip()
                sql_lines.append(clean_line)
                continue
            elif entry_pattern.match(line) or legacy_entry_pattern.match(line):
                is_sql_block = False

            if is_sql_block:
                sql_lines.append(line.strip())
            elif "FieldIndex=" in line:
                match = re.match(r".*?Name=([^;]+); Tipo=[^;]+; Value='?(.*?)'?$", line)
                if match:
                    name = match.group(1)
                    value = match.group(2)
                    if name in current_row:
                        fetch_rows.append(current_row.copy())
                        current_row.clear()
                    current_row[name] = value

            if "ORA-" in line:
                has_error = True
                error_line = line.strip()

            rc_match = re.search(r"Record Count\s*=\s*(\d+)", line)
            if rc_match:
                record_count = int(rc_match.group(1))

        if current_row:
            fetch_rows.append(current_row)

        return {
            "sql_lines": sql_lines,
            "fetch_rows": fetch_rows,
            "record_count": record_count,
            "block": block,
            "has_error": has_error,
            "error_line": error_line
        }

    parsed_blocks = [parse_block(b) for b in blocks]

    merged_blocks = []
    i = 0
    while i < len(parsed_blocks):
        current = parsed_blocks[i]
        if current["sql_lines"] and not current["fetch_rows"] and (current["record_count"] is None or current["record_count"] == 0):
            if i + 1 < len(parsed_blocks):
                next_block = parsed_blocks[i+1]
                if next_block["fetch_rows"] or (next_block["record_count"] is not None):
                    merged_sql = current["sql_lines"]
                    merged_fetch = next_block["fetch_rows"]
                    merged_record_count = next_block["record_count"]

                    merged_block = {
                        "sql_lines": merged_sql,
                        "fetch_rows": merged_fetch,
                        "record_count": merged_record_count,
                        "block": current["block"] + next_block["block"],
                        "has_error": current["has_error"] or next_block["has_error"],
                        "error_line": current["error_line"] or next_block["error_line"]
                    }
                    merged_blocks.append(merged_block)
                    i += 2
                    continue
        merged_blocks.append(current)
        i += 1

    st.sidebar.markdown("### 🔎 Filtros")
    filtro_tipo = st.sidebar.radio(
        "Mostrar consultas:",
        ["Todos", "Com resultado", "Sem resultado"]
    )

    expander_estado = st.sidebar.radio(
        "Estado dos blocos:",
        ["Recolher todos", "Expandir todos"]
    )
    expanded_global = expander_estado == "Expandir todos"

    for pb in merged_blocks:
        sql_lines = pb["sql_lines"]
        fetch_rows = pb["fetch_rows"]
        record_count = pb["record_count"]
        block = pb["block"]
        has_error = pb.get("has_error", False)
        error_line = pb.get("error_line")

        if record_count is not None:
            tem_resultado = record_count > 0
        else:
            tem_resultado = len(fetch_rows) > 0

        mostrar_bloco = (
            filtro_tipo == "Todos" or
            (filtro_tipo == "Com resultado" and tem_resultado) or
            (filtro_tipo == "Sem resultado" and not tem_resultado)
        )

        if mostrar_bloco:
            header = block[0]
            with st.expander(f"🕒 {header[:19]} - {header[22:28]}", expanded=expanded_global):
                if sql_lines:
                    raw_sql = " ".join(sql_lines)
                    formatted_sql = sqlparse.format(
                        raw_sql,
                        keyword_case='upper',
                        reindent=True,
                        indent_columns=True,
                        wrap_after=80
                    )
                    formatted_sql = re.sub(r",\s*", ",\n       ", formatted_sql)
                    st.markdown("**🔍 Consulta SQL:**")
                    st.markdown(
                        f"""
                        <div style='position:relative;'>
                            <pre style='font-size:12px; font-family: monospace; background-color:#f0f0f0; padding:10px; border-radius:5px;'>{formatted_sql}</pre>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                else:
                    if record_count is not None:
                        st.info(f"ℹ️ Quantidade de registros encontrados: {record_count}")

                if has_error and error_line:
                    st.error(f"❌ Erro detectado: {error_line}")

                if tem_resultado and fetch_rows:
                    df = pd.DataFrame(fetch_rows)
                    st.markdown("**📋 Dados do Fetch (Tabela):**")
                    st.dataframe(df, use_container_width=True)
                else:
                    record_count_zero = record_count == 0
                    if sql_lines and record_count_zero:
                        st.info("❗ A consulta foi executada, mas não retornou dados.")
else:
    st.info("👆 Faça upload de um arquivo .txt ou .log de log para visualizar.")