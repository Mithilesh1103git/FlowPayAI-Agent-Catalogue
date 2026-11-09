"""Reusable AG Grid renderer with a Streamlit dataframe fallback."""

import pandas as pd
import streamlit as st


def render_grid(data, key=None, height=360, selection="single"):
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if df.empty:
        st.info("No records to display.")
        return None
    try:
        from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, GridUpdateMode

        builder = GridOptionsBuilder.from_dataframe(df)
        builder.configure_default_column(
            resizable=True,
            sortable=True,
            filter=True,
            min_column_width=110,
            wrapText=True,
            autoHeight=True,
        )
        builder.configure_pagination(enabled=True, paginationPageSize=20)
        builder.configure_selection(selection_mode=selection, use_checkbox=False)
        builder.configure_grid_options(domLayout="normal", rowHeight=42)
        return AgGrid(
            df,
            gridOptions=builder.build(),
            height=height,
            key=key,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            allow_unsafe_jscode=False,
            theme="streamlit",
        )
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)
        return None
