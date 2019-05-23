using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using Vuforia;


public class qrstatus : MonoBehaviour {

    public Text statusText;
    public qrTrackableEventHandler QRCode;


	// Use this for initialization
	void Awake () {
        statusText.text = "Initializing...";

    }

    // Update is called once per frame
    void Update () {
        checkTracker();
	}

    void displayStatus (string message)
    {
        statusText.text = message;
    }

    void checkTracker()
    {
        if (QRCode.isTracked) {
            if (QRCode.isExtended)
                displayStatus("QRCode Lost, Extrapolating...");
            else
                displayStatus("QRCode Detected");
        }
        else
        {
            displayStatus("QRCode Not Found");
        }
    }
}