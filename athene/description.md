# Athene

Athene is an abstract entity based on the Greek goddess. The analogy I want to make is to a high-dimensional space that is alive. So we start with a simple 2D coordinate space we all know. Black background, two white lines, orthogonally crossing each other. These lines are not static, but move almost like tentacles: they move around, grow longer or shorter, change angles. But they always remain straight and connected in the middle. So like a coordinate system. 

Then a third joins. And eventually more and more. It ends up looking a little bit like a star. All the arms/coordinate planes move around and extend/shrink. The end of one edge and spawn new edges as well. 

Based on certain conditions, I want small clusters of the 4 second clips body search produces to appear, overlapping, and then disappearing again. 

The video will be synced with the voice and pre-rendered. 

## Athene Rehearsal Interactive Prototyping System

Based on the play, there will be the following moments the system will need to render: 

1. Athene with 2 Axis, moving around, probing. (athene_voice_placeholder/athene_1_kathycalm.mp3, athene_2) 
2. Athene death scene. (athene_3, athene_4, athene_5) One parent branch per cluster. Branches static in this scene:
   1. Athene with 3 Axis, first cluster of death scene rehearsal videos appear. Hold. No child branches. 
   2. Athene with 4 Axis, second cluster of DSR videos appear. Hold. No child branches. 
   3. Athene with 5 Axis, third cluster appears. Hold. No child branches. 
   4. Athene with n Axis, n cluster appears. Footage from rehearsals but also from previous wars, Gaza, Ukraine, etc. Hold. No child branches. 
3. Athene back to two Axis, moving around. (athene_6)
4. Athene grows over about 10 minutes. (athene_7, athene_8) Ever-more Axis growing, need to time how long this animation should roughly take, ever more pulsing light until it is almost stroboscopic. Ends with everything pulling together into a new shape, a new world order. For now, this shape is just a glowing circle. 

Voice recordings of 22 November (athene_voice_2211, stereo-panned), used instead of the placeholders above and of the recordings of 21 October (athene_voice_2110): athene_1_panned and athene_2_panned → scene 1, athene_3_panned → scene 2 (death scene), athene_4_panned → scene 3 (back to two axes), athene_5_panned, athene_5.5_panned_normal, then athene_6_panned twice → scene 4 (growth).

We will prototype a live page version of these Athene scenes. Once we have the final voice recordings and timing we will render the different clips. For the live localhost version I control during rehearsals, we have following key commands per scene: 

"N" - go to next scene. 
"B" - go back to previous scene
"P" - play the audio clip associated with the scene. If multiple audio clips are associated with a scene, simply play the next one in the queue of that scene. 
"Space" - reset current scene

Scene specific commands: 
2. Death Scene - "R" for a new clip cluster from rehearsal material. "O" for a new clip cluster from the online video. Reuse the clips you've created for now. 
4. "E" - triggers ending, "S" activates strobe effect. 