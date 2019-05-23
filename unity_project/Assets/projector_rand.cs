using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class projector_rand : MonoBehaviour {
	private ParticleSystem mySystem;
	private ParticleSystem.Particle[] particles;
	private int numParticles;
	private float start_time; 
	private float range_max = 0.4f; 
	private float range_min = -0.4f;
	private float curr_max;
	private float curr_min; 

	// Use this for initialization
	void Start () {
		mySystem = GetComponent<ParticleSystem> ();
		curr_max = range_max;
		curr_min = range_min;
	}
	
	// Update is called once per frame
	void Update () {
		// Initialize variables 
			numParticles = 50;
			particles = new ParticleSystem.Particle[numParticles];
			// Spawn 
			Display();
	}

	void Display(){
		if (curr_max > 0.0001 && curr_min < -0.0001){
			curr_max -= 0.0005f;
			curr_min += 0.0005f;
		}
		else{
			curr_max = range_max;
			curr_min = range_min;
		}

        // Set positions
        for (int i = 0; i < numParticles; i++)
        {
        	particles[i].startSize = 0.05f;
        	particles[i].startColor = Color.magenta;
        	particles[i].position = new Vector3(get_rand_x(curr_min, curr_max), 
            			get_rand_y(curr_min, curr_max), 0f);
        	set_color(particles[i].position.x, particles[i].position.y , i);
        }

        mySystem.SetParticles(particles, particles.Length);
	}

	float get_rand_x(float x_min, float x_max){
		return (float)(Random.Range(x_min, x_max));
	}

	float get_rand_y(float y_min, float y_max){
		return (float)(Random.Range(y_min, y_max));
	}
	void set_color(float x_pos, float y_pos, int i){
		if(Mathf.Abs(x_pos) > (range_max * 0.1) && Mathf.Abs(y_pos) > (range_max * 0.1)){
			particles[i].startColor = Color.red;
		}
		else if(Mathf.Abs(x_pos) > (range_max * 0.01) && Mathf.Abs(y_pos) > (range_max * 0.01)){
			particles[i].startColor = Color.yellow;
		}
		else {
			particles[i].startColor = Color.green;
		}

	}


}
