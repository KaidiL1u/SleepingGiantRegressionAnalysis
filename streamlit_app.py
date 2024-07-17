import streamlit as st
import pandas as pd
import statsmodels.api as sm
import numpy as np
import itertools
import warnings
import os
import time
from concurrent.futures import ThreadPoolExecutor

# Suppressing FutureWarnings regarding pandas deprecations
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)

# Predefined year selections for each window
predefined_years = {
    "2001-2023": list(range(2001, 2024)),
    "2005 - 2023 excluding 2009, 2016": [year for year in range(2005, 2024) if year not in {2009, 2016}],
    "2001-2023 excluding 2020, 2021, 2022": [year for year in range(2001, 2024) if year not in {2020, 2021, 2022}],
    "2001-2019": list(range(2001, 2020)),
    "2001-2023 excluding 2009, 2013, 2020, 2021, 2022": [year for year in range(2001, 2024) if year not in {2009, 2013, 2020, 2021, 2022}]
}

def run_single_regression(df, y_var, x_vars):
    Y = df[y_var].astype(float)
    X = df[x_vars].astype(float)
    X = sm.add_constant(X)
    model = sm.OLS(Y, X).fit()
    return model

class RegressionApp:
    def __init__(self):
        self.df = None
        self.variables = []
        self.scenarios = dict(predefined_years)
        self.num_combinations = 0
        self.total_regressions = 0
        self.completed_regressions = 0
        self.start_time = None

    def choose_file(self):
        file = st.file_uploader("Upload Excel file", type=["xlsx"])
        if file:
            self.df = pd.read_excel(file, sheet_name="Sheet1")
            self.variables = self.df.columns[2:].tolist()  # Assuming variables start from column C onwards
            st.write("### Columns in the uploaded file:")
            st.write(self.df.columns.tolist())

    def show_variable_selection(self):
        if self.df is None:
            st.warning("Please upload an Excel file first.")
            return

        self.variables = self.df.columns[2:].tolist()  # Assuming variables start from column C onwards
        self.num_combinations = sum([len(list(itertools.combinations(self.variables, i))) for i in range(1, len(self.variables) + 1)])
        self.total_regressions = 5 * self.num_combinations

        st.subheader(f"{len(self.variables)} variables found.")
        st.subheader(f"Regression will create {self.num_combinations} variable combinations (Total Regressions: {self.total_regressions}).")

        st.write("### Variables:")
        for var in self.variables:
            st.write(f"- {var}")

    def display_scenarios(self):
        all_years = list(range(2001, 2024))
        scenario_df = pd.DataFrame(columns=all_years)

        for name, years in self.scenarios.items():
            scenario_df.loc[name] = ['•' if year in years else '' for year in all_years]

        st.table(scenario_df.T)

    def run_regression_scenarios(self):
        if self.df is None:
            st.warning("Please upload an Excel file first.")
            return

        # Check if 'Year' column exists
        if 'Year' not in self.df.columns:
            st.error("The 'Year' column is missing from the uploaded file.")
            return

        all_results = []

        self.start_time = time.time()

        progress_bar = st.progress(0)
        progress_text = st.empty()

        def process_scenario(scenario_name, years):
            if not years:  # If years selection is empty, use predefined years
                years = predefined_years[scenario_name]

            df_selected = self.df[self.df['Year'].isin(years)]
            variables = self.df.columns[2:].tolist()  # Assuming variables start from column C onwards
            num_variables = len(variables)

            combinations = list(itertools.chain_from_iterable(
                itertools.combinations(variables, r) for r in range(1, num_variables + 1)
            ))

            scenario_results = []

            for idx, selected_x_vars in enumerate(combinations, start=1):
                model = run_single_regression(df_selected, self.df.columns[1], list(selected_x_vars))
                output_df = self.format_regression_output(model)
                anova_table = self.calculate_anova_table(model)
                scenario_results.append((output_df, years, self.df.columns[1], model, anova_table, selected_x_vars, idx))
                self.completed_regressions += 1
                self.update_progress(progress_bar, progress_text)

            return scenario_name, scenario_results

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_scenario, scenario_name, years) for scenario_name, years in self.scenarios.items()]
            for future in futures:
                all_results.append(future.result())

        self.prepare_downloads(all_results)
        self.show_combined_results_window(all_results)

    def update_progress(self, progress_bar, progress_text):
        if self.total_regressions == 0:
            return
        progress_percent = self.completed_regressions / self.total_regressions
        elapsed_time = time.time() - self.start_time
        estimated_total_time = (elapsed_time / self.completed_regressions) * self.total_regressions if self.completed_regressions > 0 else 0
        time_left = estimated_total_time - elapsed_time

        progress_bar.progress(progress_percent)
        progress_text.text(f"Completed {self.completed_regressions} out of {self.total_regressions} regressions. "
                           f"Time left: {time_left:.2f} seconds. Records left to run: {self.total_regressions - self.completed_regressions}.")

    def prepare_downloads(self, all_results):
        st.session_state["download_links"] = {}
        for scenario_name, scenario_results in all_results:
            summary_data = []
            for result in scenario_results:
                output_df, selected_years, y_variable_name, model, anova_table, selected_x_vars, idx = result

                # Add selected years at the top
                summary_data.append(['', 'Selected Years', ', '.join(map(str, selected_years))])
                summary_data.append(['', 'SUMMARY OUTPUT', ''])

                summary_data.append(['', 'Regression Statistics', ''])
                summary_data.append(['', 'Multiple R', f"{model.rsquared ** 0.5:.4f}"])
                summary_data.append([f"S{idx}R^2", 'R Square', f"{model.rsquared:.4f}"])
                summary_data.append(['', 'Adjusted R Square', f"{model.rsquared_adj:.4f}"])
                summary_data.append([f"S{idx}SE", 'Standard Error of the Regression', f"{model.scale ** 0.5:.4f}"])
                summary_data.append(['', 'Observations', f"{int(model.nobs)}"])

                # Add ANOVA table
                summary_data.append(['', 'ANOVA', ''])
                summary_data.append(['', '', 'df', 'SS', 'MS', 'F', 'Significance F'])
                for index, row in anova_table.iterrows():
                    summary_data.append(['', str(index)] + [str(item) if item is not None else '' for item in row.tolist()])

                # Add coefficients if available
                coeff_table = pd.read_html(model.summary().tables[1].as_html(), header=0, index_col=0)[0].reset_index()
                summary_data.append(['', '', 'Coefficients', 'Standard Error', 't Stat', 'P-value', 'Lower 95%', 'Upper 95%'])

                # Separate 'Constant' and other variables
                constant_row = coeff_table[coeff_table.iloc[:, 0] == 'const'].iloc[0].tolist()
                x_vars = coeff_table[coeff_table.iloc[:, 0] != 'const'].iloc[:, 0].tolist()

                # Sort remaining x variables alphabetically
                x_vars_sorted = sorted(x_vars)

                # Add 'Constant' first
                summary_data.append([f"S{idx}Const"] + [str(item) if item is not None else '' for item in constant_row])

                # Add sorted x variables
                for i, var in enumerate(x_vars_sorted, start=1):
                    row = coeff_table[coeff_table.iloc[:, 0] == var].iloc[0].tolist()
                    summary_data.append([f"S{idx}X{i}"] + [str(item) if item is not None else '' for item in row])

            summary_df = pd.DataFrame(summary_data)
            excel_filename = f"{scenario_name}.xlsx"
            with pd.ExcelWriter(excel_filename, engine='xlsxwriter') as writer:
                summary_df.to_excel(writer, sheet_name="Sheet1", index=False)
            st.session_state["download_links"][scenario_name] = excel_filename

    def show_combined_results_window(self, all_results):
        st.session_state["results"] = all_results
        st.experimental_rerun()

    def display_results_page(self):
        if "results" not in st.session_state:
            st.write("No results to display. Please run the regression scenarios first.")
            return

        all_results = st.session_state["results"]

        # Prepare to display up to 5 scenarios
        num_tabs = min(5, len(all_results))
        tab_titles = [f"Scenario: {name}" for name, _ in all_results[:num_tabs]]
        tabs = st.tabs(tab_titles)

        for tab, (scenario_name, scenario_results) in zip(tabs, all_results[:num_tabs]):
            with tab:
                summary_data = []

                for result in scenario_results:
                    output_df, selected_years, y_variable_name, model, anova_table, selected_x_vars, idx = result

                    # Add selected years at the top
                    summary_data.append(['', 'Selected Years', ', '.join(map(str, selected_years))])
                    summary_data.append(['', 'SUMMARY OUTPUT', ''])

                    summary_data.append(['', 'Regression Statistics', ''])
                    summary_data.append(['', 'Multiple R', f"{model.rsquared ** 0.5:.4f}"])
                    summary_data.append([f"S{idx}R^2", 'R Square', f"{model.rsquared:.4f}"])
                    summary_data.append(['', 'Adjusted R Square', f"{model.rsquared_adj:.4f}"])
                    summary_data.append([f"S{idx}SE", 'Standard Error of the Regression', f"{model.scale ** 0.5:.4f}"])
                    summary_data.append(['', 'Observations', f"{int(model.nobs)}"])

                    # Add ANOVA table
                    summary_data.append(['', 'ANOVA', ''])
                    summary_data.append(['', '', 'df', 'SS', 'MS', 'F', 'Significance F'])
                    for index, row in anova_table.iterrows():
                        summary_data.append(['', str(index)] + [str(item) if item is not None else '' for item in row.tolist()])

                    # Add coefficients if available
                    coeff_table = pd.read_html(model.summary().tables[1].as_html(), header=0, index_col=0)[0].reset_index()
                    summary_data.append(['', '', 'Coefficients', 'Standard Error', 't Stat', 'P-value', 'Lower 95%', 'Upper 95%'])

                    # Separate 'Constant' and other variables
                    constant_row = coeff_table[coeff_table.iloc[:, 0] == 'const'].iloc[0].tolist()
                    x_vars = coeff_table[coeff_table.iloc[:, 0] != 'const'].iloc[:, 0].tolist()

                    # Sort remaining x variables alphabetically
                    x_vars_sorted = sorted(x_vars)

                    # Add 'Constant' first
                    summary_data.append([f"S{idx}Const"] + [str(item) if item is not None else '' for item in constant_row])

                    # Add sorted x variables
                    for i, var in enumerate(x_vars_sorted, start=1):
                        row = coeff_table[coeff_table.iloc[:, 0] == var].iloc[0].tolist()
                        summary_data.append([f"S{idx}X{i}"] + [str(item) if item is not None else '' for item in row])

                summary_df = pd.DataFrame(summary_data)
                st.dataframe(summary_df)

                # Provide direct download link
                if scenario_name in st.session_state["download_links"]:
                    excel_filename = st.session_state["download_links"][scenario_name]
                    with open(excel_filename, 'rb') as f:
                        data = f.read()
                    st.download_button(label=f"Download {scenario_name} as Excel", data=data, file_name=excel_filename)

    def run_regression(self, df):
        Y = df[self.df.columns[1]].astype(float)
        X = df[df.columns.difference(['Year', self.df.columns[1]])].astype(float)
        X = sm.add_constant(X)
        model = sm.OLS(Y, X).fit()
        return model

    def format_regression_output(self, model):
        summary_df = pd.read_html(model.summary().tables[1].as_html(), header=0, index_col=0)[0]
        return summary_df

    def calculate_anova_table(self, model):
        sse = model.ssr  # Sum of squared residuals
        ssr = model.ess  # Explained sum of squares
        sst = ssr + sse  # Total sum of squares
        dfe = model.df_resid  # Degrees of freedom for error
        dfr = model.df_model  # Degrees of freedom for regression
        dft = dfr + dfe  # Total degrees of freedom

        mse = sse / dfe  # Mean squared error
        msr = ssr / dfr  # Mean squared regression

        f_stat = msr / mse  # F-statistic
        p_value = model.f_pvalue  # P-value for the F-statistic

        anova_table = pd.DataFrame({
            'df': [dfr, dfe, dft],
            'SS': [ssr, sse, sst],
            'MS': [msr, mse, np.nan],
            'F': [f_stat, np.nan, np.nan],
            'Significance F': [f"{p_value:.4f}", np.nan, np.nan]
        }, index=['Regression', 'Residual', 'Total'])

        return anova_table

def main():
    st.set_page_config(layout="wide")

    app = RegressionApp()

    st.title("SG2024 Regression Analysis Crazy-Fast Tool")

    st.write("### Upload Xlsx Source File:")
    app.choose_file()

    if st.button("Run Regression Scenarios"):
        with st.spinner("Running regression scenarios..."):
            app.run_regression_scenarios()

    if "progress_text" in st.session_state:
        st.write(st.session_state.progress_text)

    st.write("### Existing Scenarios:")
    app.display_scenarios()

    st.write("### Variables:")
    app.show_variable_selection()

    if "results" in st.session_state:
        app.display_results_page()

if __name__ == "__main__":
    main()
