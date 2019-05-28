using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

public class ButtonControl : MonoBehaviour
{

    public WebRequest commands; 

    // Start is called before the first frame update
    void Start()
    {
        Button[] buttons;
        buttons = GetComponentsInChildren<Button>();

        foreach (Button b in buttons)
        {
            addListener(b);
            b.tag = "ButtonPage1";
            Debug.Log(b.name);
        }

    }

    void addListener(Button buttonA)
    {
        buttonA.onClick.AddListener(() => taskOnClick(buttonA.name));
    }

    // ERROR: NOT RECOGNIZING THE BACK BUTTON EVEN THOUGH IT ADDS A LISTENER???
    void taskOnClick(string button_name)
    {
        Debug.Log("You clicked on: ");
        Debug.Log(button_name);
        commands.NextCommand(button_name);
    }

    // Update is called once per frame
    void Update()
    {
        
    }
}
