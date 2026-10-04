"""Screening names against OFAC's sanctions lists (the PATRIOT/OFAC search).

Lists come from the U.S. Treasury's Sanctions List Service (public domain): the
Specially Designated Nationals list and the consolidated non-SDN lists. Matching is
designed to miss nothing a reviewer must see while raising as few false alarms as
possible: OFAC's own weak-alias flags, an index over several name keys, token
alignment weighted by how common each name is in the United States, and context
such as entity type and date of birth. It never clears anyone on its own; every
candidate carries the reasons for its score, for a person to decide.
"""
