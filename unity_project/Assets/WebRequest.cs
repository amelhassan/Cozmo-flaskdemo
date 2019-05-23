using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

public class WebRequest : MonoBehaviour {

	// Use this for initialization
	void Start () {

		// A correct website page -> call function below
        StartCoroutine(GetRequest("https://ar-education.herokuapp.com"));

	}
	
	// Update is called once per frame
	void Update () {
	}

	IEnumerator GetRequest(string uri)
    {
        using (UnityWebRequest WebRequest_ins = UnityWebRequest.Get(uri))
        {
            // Request and wait for the desired page.
            yield return WebRequest_ins.SendWebRequest();

            if (WebRequest_ins.isNetworkError)
            {
                Debug.Log(": Error: " + WebRequest_ins.error);
            }
            else
            {
                Debug.Log(":\nReceived: " + WebRequest_ins.downloadHandler.text);
            }
        }
    }
}
