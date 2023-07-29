# -*- encoding: utf-8 -*-
# @Author: SWHL
# @Contact: liekkaskono@163.com
import shutil
import time
from pathlib import Path

import streamlit as st

from knowledge_qa_llm.file_loader import FileLoader
from knowledge_qa_llm.llm import ChatGLM26B
from knowledge_qa_llm.utils import get_timestamp, logger, make_prompt, mkdir, read_yaml
from knowledge_qa_llm.vector_utils import DBUtils, EncodeText

config = read_yaml("knowledge_qa_llm/config.yaml")
upload_dir = config.get("upload_dir")

st.set_page_config(
    page_title=config.get("title"),
    page_icon=":robot:",
)


def init_sidebar():
    st.sidebar.markdown("### 🛶 参数设置")
    param = config.get("Parameter")

    param_max_length = param.get("max_length")
    max_length = st.sidebar.slider(
        "max_length",
        min_value=param_max_length.get("min_value"),
        max_value=param_max_length.get("max_value"),
        value=param_max_length.get("default"),
        step=param_max_length.get("step"),
        help=param_max_length.get("tip"),
    )

    st.session_state["params"] = {}
    st.session_state["params"]["max_length"] = max_length

    param_top = param.get("top_p")
    top_p = st.sidebar.slider(
        "top_p",
        min_value=param_top.get("min_value"),
        max_value=param_top.get("max_value"),
        value=param_top.get("value"),
        step=param_top.get("step"),
        help=param_top.get("tip"),
    )
    st.session_state["params"]["top_p"] = top_p

    param_temp = param.get("temperature")
    temperature = st.sidebar.slider(
        "temperature",
        min_value=param_temp.get("min_value"),
        max_value=param_temp.get("max_value"),
        value=param_temp.get("value"),
        step=param_temp.get("stemp"),
        help=param_temp.get("tip"),
    )
    st.session_state["params"]["temperature"] = temperature

    st.sidebar.markdown("### 🧻 知识库")
    uploaded_files = st.sidebar.file_uploader(
        "default",
        accept_multiple_files=True,
        label_visibility="hidden",
        help="支持多选",
    )

    btn_upload = st.sidebar.button("上传文档并加载数据库", use_container_width=True)
    if btn_upload:
        time_stamp = get_timestamp()
        save_dir = Path(upload_dir) / time_stamp
        st.session_state["upload_dir"] = save_dir

        for file in uploaded_files:
            bytes_data = file.getvalue()

            mkdir(save_dir)
            save_path = save_dir / file.name
            with open(save_path, "wb") as f:
                f.write(bytes_data)
        tips("上传完毕！")

        doc_dir = st.session_state["upload_dir"]
        all_doc_contents = file_loader(doc_dir)
        for file_path, one_doc_contents in all_doc_contents.items():
            embeddings = embedding_extract(one_doc_contents)
            db_tools.insert(file_path, embeddings, one_doc_contents)

        shutil.rmtree(doc_dir.resolve())
        tips("已经加载并存入数据库中，可以提问了！")


def init_state():
    if "history" not in st.session_state:
        st.session_state["history"] = []

    if "openai_state" not in st.session_state:
        st.session_state["openai_state"] = []

    if "input_txt" not in st.session_state:
        st.session_state["input_txt"] = ""


@st.cache_resource
def init_encoder(model_path: str):
    return EncodeText(model_path)


def predict(
    text,
    model,
    custom_prompt=None,
):
    logger.info(f"Using {type(model).__name__}")

    query_embedding = embedding_extract(text)
    with st.spinner("从文档中搜索相关内容"):
        search_res, search_elapse = db_tools.search_local(query_embedding)

    context = "\n".join(sum(search_res.values(), []))
    res_cxt = f"**从文档中检索到的相关内容Top5\n(相关性从高到低，耗时:{search_elapse:.5f}s):** \n"
    bot_print(res_cxt)

    for file, content in search_res.items():
        content = "\n".join(content)
        one_context = f"**来自文档：《{file}》** \n{content}"
        bot_print(one_context)

        logger.info(f"上下文：\n{one_context}\n")

    if len(context) <= 0:
        bot_print("从文档中搜索相关内容为空，暂不能回答该问题")
    else:
        response, elapse = get_model_response(text, context, custom_prompt, model)
        print_res = f"**使用模型：{select_model}**\n**模型推理耗时：{elapse:.5f}s**"
        bot_print(print_res)
        bot_print(response)


def bot_print(content):
    with st.chat_message("assistant", avatar="🤖"):
        message_placeholder = st.empty()
        full_response = ""
        for chunk in content.split():
            full_response += chunk + " "
            time.sleep(0.05)
            message_placeholder.markdown(full_response + "▌")
        message_placeholder.markdown(full_response)


def get_model_response(text, context, custom_prompt, model):
    params_dict = st.session_state["params"]

    s_model = time.perf_counter()
    prompt_msg = make_prompt(text, context, custom_prompt)
    logger.info(f"最终拼接后的文本：\n{prompt_msg}\n")

    response = model(prompt_msg, history=None, **params_dict)
    elapse = time.perf_counter() - s_model

    logger.info(f"模型回答: \n{response}\n")
    if not response:
        response = "抱歉，未能正确回答该问题"
    return response, elapse


def tips(txt: str, wait_time: int = 2, icon: str = "🎉"):
    st.toast(txt, icon=icon)
    time.sleep(wait_time)


if __name__ == "__main__":
    file_loader = FileLoader()

    db_path = config.get("vector_db_path")
    db_tools = DBUtils(db_path)

    encoder_model_path = config.get("encoder_model_path")
    embedding_extract = init_encoder(encoder_model_path)

    chatglm26b = ChatGLM26B(config.get("llm_api_url"))

    init_sidebar()
    init_state()

    title = config.get("title")
    version = config.get("version", "0.0.1")
    st.markdown(
        f"<h3 style='text-align: center;'>{title} v{version}</h3><br/>",
        unsafe_allow_html=True,
    )

    MODEL_OPTIONS = {
        "ChatGLM2-6B": chatglm26b,
    }

    PLUGINS_OPTIONS = {
        "文档": 3,
        "模型本身": 0,
    }

    menu_col1, menu_col2 = st.columns([5, 5])
    select_model = menu_col1.selectbox("🎨基础模型：", MODEL_OPTIONS.keys())
    select_plugin = menu_col2.selectbox("🛠Plugin：", PLUGINS_OPTIONS.keys())

    input_prompt_container = st.container()
    with input_prompt_container:
        with st.expander("💡Prompt", expanded=False):
            text_area = st.empty()
            input_prompt = text_area.text_area(
                label="输入",
                max_chars=500,
                height=200,
                label_visibility="hidden",
                value=config.get("DEFAULT_PROMPT"),
                key="input_prompt",
            )

    input_txt = st.chat_input("What is up?")
    if input_txt:
        with st.chat_message("user", avatar="😀"):
            st.markdown(input_txt)

        plugin_id = PLUGINS_OPTIONS[select_plugin]
        llm = MODEL_OPTIONS[select_model]

        if not input_prompt:
            input_prompt = config.get("DEFAULT_PROMPT")

        if plugin_id == 3:
            predict(
                input_txt,
                llm,
                input_prompt,
            )
