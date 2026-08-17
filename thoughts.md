Palantir's Ontology: data, logic, action

What data are we collecting? Are we focusing on the actors, or on the room as such? 

GOAL: teach the system how to decide how to handle conflicts? Learn about human decision making? Perhaps this mirrors the dramaturgy somewhat -> start with the data collection/learning, at some point though the system learns to make its own decisions on how to handle a conflict. 
-> [#TODO]: what does this need to be a smart critique of how autonomous systems learn and what the ethical implications are? 

FUNCTIONALITY - VS - FAKING CONUNDRUM: same conversation around each production: how much of this system do we really need to build, how much of it do we fake? The software is in service of the production. To that end, 
*smart search of footage* is essential. That would allow Alessa, Nils, Yäel & myself to sift through & find material for the play. 
*LLM for profiling* provides interesting results. Develop this in Absprache with Sara, perhaps use the LLM output for the "voice" of the system
*CV aesthetic* run & render CV algorithims over the footage to be used in the production (e.g. face detection, object recognition etc.) 
Stuff like emotion recognition, profiling labels like 'threat' etc. as well as behavioural prediction + any decision the system might make should be faked in my opinion, as we want to control the dramaturgy of the piece. Furthermore, there is no benefit to doing it live beyond the conceptual neatness of it. 

ON SMART SEARCHING FOOTAGE 
The requirments here are different than for most smart search AV tools. We are collecting footage only in the rehearsal space, so theoretically we could map the actors movements in the space quite accurately, using the exact meausurments of the Probebühne to construct a digital twin. 

*Search via text*: theoretically, searching a line from the play should get you all the "takes" of that line + ones that were similar based on nearest-neighbour searches. 

*Search via audio (live)*: using STT, the actor "conjures" previous "takes" of what they just said. 

*Search via body (live)*: using pose-estimation (e.g. via custom feature extractor in WISE), the actor "conjures" previous "takes" of the gesture they just made. This in particular fits well to the conflict-theme of Elektra: recognising not just the pose but also interpreting it. 

In general, the smart search is not only about finding the similar moments, but also *judging* them and *drawing conclusions*. 