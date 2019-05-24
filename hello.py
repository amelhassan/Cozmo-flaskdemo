from flask import Flask, request
app = Flask(__name__)
printed = 'Hello World\n'

@app.route('/', methods = ['GET', 'POST'])
def hello_world():
    global printed 
    if request.method == 'POST':
        printed = request.form['message'] 
    return printed

if __name__ == '__main__':
    # printed = "start"
    app.run(debug=True) 