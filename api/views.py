from django.shortcuts import render
import pandas as pd
import sqlite3
import re
import google.generativeai as genai
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.files.storage import default_storage
import os
# Configure Google Generative AI
genai.configure(api_key="AIzaSyCWf0aLUCsFx2ec8sW6sWh5MhhzkfOlf1w")
model = genai.GenerativeModel('gemini-1.5-flash')


DB_PATH = "uploaded_data.db"

# Utility function for creating a persistent SQLite database
def create_sqlite_db(df):
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('data', conn, index=False, if_exists='replace')
    conn.close()

class UploadData(APIView):
    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        
        file_extension = file.name.split('.')[-1]
        try:
            if file_extension == 'csv':
                df = pd.read_csv(file, engine='python', on_bad_lines='skip')
            elif file_extension in ['xlsx', 'xls']:
                df = pd.read_excel(file)
            else:
                return Response({"error": "Unsupported file type"}, status=status.HTTP_400_BAD_REQUEST)
            
            if df.empty:
                return Response({"error": "Uploaded file is empty or not readable"}, status=status.HTTP_400_BAD_REQUEST)

            # Save DataFrame to a persistent SQLite database
            create_sqlite_db(df)
            columns = list(df.columns)
            return Response({"message": "File uploaded successfully", "columns": columns})
        
        except Exception as e:
            return Response({"error": f"Failed to process file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class ProcessQuery(APIView):
    def post(self, request):
        prompt = request.data.get('prompt')
        if not prompt:
            return Response({"error": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Connect to the persistent SQLite database
        conn = sqlite3.connect(DB_PATH)
        queries = re.split(r'\band\b', prompt)
        results = []

        for query in queries:
            query = query.strip()
            prompt_text = f"Convert this prompt to SQL query: '{query}'"
            response = model.generate_content(prompt_text)
            sql_query = response.text.strip().replace("```", "")
            
            # Execute the SQL query
            try:
                result_df = pd.read_sql_query(sql_query, conn)
                results.append(result_df.to_dict(orient='records'))
            except Exception as e:
                conn.close()
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        conn.close()
        return Response({"results": results})


class GetChartRecommendations(APIView):
    def post(self, request):
        user_prompt = request.data.get("prompt", "")
        
        # Check if user_prompt is empty and return an error if so
        if not user_prompt:
            return Response({"error": "Prompt cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)

        # Step 1: Prepare sample data and generate SQL Query Prompt
        try:
            # Connect to the database and fetch a sample of the data
            conn = sqlite3.connect(DB_PATH)
            sample_df = pd.read_sql_query("SELECT * FROM data LIMIT 10", conn)  # Get a sample of the first 10 rows
            sample_data = sample_df.to_json(orient='records')
            conn.close()

            # Formulate the prompt with the sample data to help the model understand the database structure
            sql_prompt = (
                f"Based on the user's request, generate a meaningful SQL query. The user asked: '{user_prompt}'. "
                f"Here is a sample of the data in the table 'data' to give you context:\n\n{sample_data}\n\n"
                f"Use this sample structure to generate an accurate SQL query that will retrieve data relevant to the user's request."
            )
            
            # Send the prompt to the model to generate SQL
            sql_response = model.generate_content(sql_prompt)
            sql_text = sql_response.text if hasattr(sql_response, 'text') else sql_response.generated_text
            
            # Extract SQL query from the response, removing any extraneous markdown formatting
            sql_query_match = re.search(r'```sql\s*(.*?)\s*```', sql_text, re.DOTALL)
            sql_query = sql_query_match.group(1).strip() if sql_query_match else sql_text.strip()
            print("Generated SQL Query:", sql_query)
        
        except Exception as e:
            print("Error generating SQL:", str(e))
            return Response({"error": "Failed to generate SQL query"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Step 2: Execute SQL Query in SQLite
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query(sql_query, conn)
            conn.close()
            print("Executed SQL Query successfully")
        
        except Exception as e:
            print("Error executing SQL Query:", str(e))
            return Response({"error": f"Failed to execute SQL query: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Step 3: Generate JSON-Compatible Chart Recommendations
        chart_prompt = (
            f"Recommend suitable chart types and necessary data columns for visualizing the following data:\n\n"
            f"{df.head(10).to_json(orient='records')}"
        )
        
        try:
            chart_response = model.generate_content(chart_prompt)
            # Remove any markdown formatting from the recommendations for JSON compatibility
            recommended_charts = chart_response.text.strip() if hasattr(chart_response, 'text') else chart_response.generated_text.strip()
            recommended_charts = re.sub(r"##.*?\n|\*|-", "", recommended_charts)  # Remove headers and bullets
            print("Generated Chart Recommendations:", recommended_charts)
        
        except Exception as e:
            print("Error generating chart recommendations:", str(e))
            return Response({"error": "Failed to generate chart recommendations"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "columns": list(df.columns),
            "rows": df.to_dict(orient="records"),
            "chart_recommendations": recommended_charts
        }, status=status.HTTP_200_OK)
