using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI; 

public class WebRequest : MonoBehaviour {

	// Use this for initialization
	void Start () {

        // A correct website page -> call function below
        //  StartCoroutine(GetRequest("https://ar-education.herokuapp.com"));
        Debug.Log("In Start\n"); 
        StartCoroutine(Pause("X")); 
       // PostRequest("http://localhost:5000/", "W");
    }
	
    public void NextCommand(string buttonA)
    {
        if (buttonA == "Forwards")
        {
            StartCoroutine(Pause("W"));
        }
        else if (buttonA == "Backwards")
        {
            StartCoroutine(Pause("S"));
        }
        else if (buttonA == "LeftTurn")
        {
            StartCoroutine(Pause("A"));
        }
        else
        {
            StartCoroutine(Pause("D"));
        }

        //StartCoroutine(Pause("X"));
    }


    // QUESTION: MAYBE LEAVE THIS EMPTY BECAUSE IT'S TOO FAST FOR THE ROBOT AND
    //          JUST USE A PUBLIC FUNCTION THAT IS CALLED WHEN SOMEONE CLICKS 
    // Update is called once per frame
    void Update () {
       // Debug.Log("In update\n"); 
       // StartCoroutine(Pause("X"));
        //Debug.Log("After first stop\n"); 
        //Pause("W");
        //Debug.Log("After second go\n"); 
        //Pause("X");
        //Debug.Log("After second stop\n"); 
       // StartCoroutine(PostRequest("http://localhost:5000/", "X"));
    }

    IEnumerator Pause(string command)
    {
        //for(; ; )
        //{
        Debug.Log("WAIIITTT\n");
        yield return new WaitForSeconds(3);
        StartCoroutine(PostRequest("http://localhost:5000/", command));
            
        //}
    }

    //IEnumerator GetRequest(string uri)
    //{
    //    using (UnityWebRequest WebRequest_ins = UnityWebRequest.Get(uri))
    //    {
    //        // Request and wait for the desired page.
    //        yield return WebRequest_ins.SendWebRequest();

    //        if (WebRequest_ins.isNetworkError)
    //        {
    //            Debug.Log(": Error: " + WebRequest_ins.error);
    //        }
    //        else
    //        {
    //            Debug.Log(":\nReceived: " + WebRequest_ins.downloadHandler.text);
    //        }
    //    }
    //}
    IEnumerator PostRequest(string uri, string data)
    {
        //string to_post = "Patience is a virtue\n";

        Dictionary<string, string> to_post = new Dictionary<string, string>();
        to_post.Add("message", data);

        using (UnityWebRequest WebRequest_out = UnityWebRequest.Post(uri, to_post))
        {
            // One website suggested adding this but it didn't seem to do anything? 
            // I'm leaving it here in case it could be helpful in the future
            // WebRequest_out.chunkedTransfer = false;

            yield return WebRequest_out.SendWebRequest();

            if (WebRequest_out.isNetworkError || WebRequest_out.isHttpError)
            {
                Debug.Log(": Error: " + WebRequest_out.error);
            }
            else
            {
                Debug.Log(":\nPrinted: " + WebRequest_out.downloadHandler.text);
            }
        }
    }

}
