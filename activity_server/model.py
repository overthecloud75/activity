from pymongo import MongoClient

# database 
mongoClient = MongoClient('mongodb://localhost:27017/')
db = mongoClient['activity']




