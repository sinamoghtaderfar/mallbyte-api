
import requests

url = "http://127.0.0.1:8000/api/auth/profile/"
headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzczMTg3NTE1LCJpYXQiOjE3NzMxMDExMTUsImp0aSI6IjRjZDg4ZDRlM2I3NDRjYTZhZGRkZDJjYzRmYjE1ZWY5IiwidXNlcl9pZCI6IjIifQ.a6L-Y7q2H9TJe_bjxTBnlZmwxvBIhmsfnO7t-H_mRFw"}

response = requests.get(url, headers=headers)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")
